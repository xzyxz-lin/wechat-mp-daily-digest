#!/usr/bin/env python3
"""
论文观察台 - 本地 Web 管理后端（纯标准库，零依赖）。

仿照「Project Atlas 项目文件总控」的架构：BaseHTTPRequestHandler + ThreadingHTTPServer。

数据源：本地存档目录 A:\\研零课题\\研零课题资料\\每日推送\\每日论文推送\\YYYY.M.D\\articles.json
信息源分两类，每篇文章带 category 字段：
  - 公众号：微信读书订阅，经 WeWe RSS 抓取
  - 期刊：各出版商 RSS 直连抓取（scripts/fetch_journals.py）

API：
  GET  /api/health          健康检查
  GET  /api/overview        总览（按分类汇总：公众号 / 期刊 + 全局统计）
  GET  /api/accounts        信息源列表（带 category）
  GET  /api/articles        文章列表（?account=&category=&page=&size=）
  GET  /api/dates           某来源的日期列表（?account=）
  POST /api/fetch           触发现场抓取（后台跑 daily.py --force）
  GET  /api/fetch/status    现场抓取状态
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import threading
import urllib.request
import ssl
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
CONFIG_PATH = PROJECT_DIR / "config" / "config.json"
JOURNALS_CONFIG_PATH = PROJECT_DIR / "config" / "journals.json"
SCRIPTS_DIR = PROJECT_DIR / "scripts"
PYTHON_EXE = SCRIPTS_DIR / ".venv" / "Scripts" / "python.exe"
DAILY_PY = SCRIPTS_DIR / "daily.py"
FUNDS_PATH = PROJECT_DIR / "data" / "funds.json"
DELETED_PATH = PROJECT_DIR / "data" / "deleted.json"
SNAPSHOTS_PATH = PROJECT_DIR / "data" / "snapshots.json"
DELETION_AUDIT_PATH = PROJECT_DIR / "data" / "deletion_audit.json"

_config: dict = {}
ARCHIVE_DIR: Path = Path(".")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def reload_paths():
    global ARCHIVE_DIR
    _config = load_config()
    ARCHIVE_DIR = Path(_config["output"]["local_dir"])


def load_journals_config() -> list:
    """读取 config/journals.json 中的期刊清单（可提交、无敏感信息）。"""
    if not JOURNALS_CONFIG_PATH.exists():
        return []
    try:
        with open(JOURNALS_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("journals", [])
    except Exception:
        return []


FETCH_STATE: dict = {
    "running": False,
    "startedAt": None,
    "finishedAt": None,
    "output": "",
    "code": None,
}
FETCH_LOCK = threading.Lock()

# 基金抓取状态（独立于论文抓取）
FUNDS_FETCH_STATE: dict = {
    "running": False,
    "startedAt": None,
    "finishedAt": None,
    "output": "",
    "code": None,
}
FUNDS_FETCH_LOCK = threading.Lock()


def scan_archive() -> dict:
    """扫描存档目录，返回 {date_str: [articles]}（日期倒序）。

    每篇文章附加稳定 id（article_uid），并过滤掉已标记删除的文章。
    """
    result: dict = {}
    deleted = set(load_deleted().get("articles", []))
    if not ARCHIVE_DIR.is_dir():
        return result
    for day_dir in ARCHIVE_DIR.iterdir():
        if not day_dir.is_dir():
            continue
        jp = day_dir / "articles.json"
        if jp.exists():
            try:
                arts = json.load(open(jp, "r", encoding="utf-8"))
            except Exception:
                arts = []
            kept = []
            for a in arts:
                a = dict(a)
                uid = article_uid(a)
                a["id"] = uid
                if uid in deleted:
                    continue
                kept.append(a)
            result[day_dir.name] = kept
    return dict(sorted(result.items(), key=lambda kv: _date_key(kv[0]), reverse=True))


def _date_key(date_str: str) -> str:
    """把 2026.8.13 归一化为可排序的 2026-08-13。"""
    parts = date_str.split(".")
    if len(parts) == 3:
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return date_str


# ===== 删除索引（标记删除，非物理删除，可恢复）=====
def load_deleted() -> dict:
    if not DELETED_PATH.exists():
        return {"articles": [], "funds": []}
    try:
        with open(DELETED_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("articles", [])
        d.setdefault("funds", [])
        return d
    except Exception:
        return {"articles": [], "funds": []}


def save_deleted(d: dict) -> None:
    try:
        with open(DELETED_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ===== 删除对账（保留删除操作记录，不影响可恢复的删除索引）=====
def load_deletion_audit() -> dict:
    if not DELETION_AUDIT_PATH.exists():
        return {}
    try:
        with open(DELETION_AUDIT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_deletion_audit(audit: dict) -> None:
    try:
        with open(DELETION_AUDIT_PATH, "w", encoding="utf-8") as f:
            json.dump(audit, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def record_deletions(kind: str, ids: list, records: list | None = None) -> None:
    """记录本次新标记删除的项目，供每日拉取/删除对账使用。"""
    if not ids:
        return
    records_by_id = {
        str(item.get("id")): item for item in (records or [])
        if isinstance(item, dict) and item.get("id")
    }
    audit = load_deletion_audit()
    today = _today_str()
    day = audit.setdefault(today, {"date": today, "events": []})
    events = day.setdefault("events", [])
    timestamp = now_iso()
    for item_id in ids:
        source = records_by_id.get(str(item_id), {})
        event = {
            "id": str(item_id),
            "kind": kind,
            "deleted_at": timestamp,
        }
        if kind == "article":
            event.update({
                "title": str(source.get("title") or "未命名文章"),
                "category": str(source.get("category") or "公众号"),
                "account": str(source.get("account") or "未知来源"),
                "archive_date": str(source.get("archive_date") or ""),
            })
        else:
            event.update({
                "title": str(source.get("project_name") or "未命名基金项目"),
                "category": "基金",
            })
        events.append(event)
    day["updated_at"] = timestamp
    save_deletion_audit(audit)


def deletion_audit_summary(target_date: str | None = None) -> dict:
    """返回指定操作日的删除统计；日期为空时取今天。"""
    target_date = target_date or _today_str()
    day = load_deletion_audit().get(target_date, {})
    events = day.get("events", []) if isinstance(day, dict) else []
    events = [event for event in events if isinstance(event, dict)]
    article_events = [event for event in events if event.get("kind") == "article"]
    fund_events = [event for event in events if event.get("kind") == "fund"]
    same_archive_day = [event for event in article_events if event.get("archive_date") == target_date]
    return {
        "date": target_date,
        "total": len(events),
        "article_count": len(article_events),
        "fund_count": len(fund_events),
        "same_archive_article_count": len(same_archive_day),
        "recent": list(reversed(events[-8:])),
        "updated_at": day.get("updated_at") if isinstance(day, dict) else None,
    }


# ===== 每日快照（抓取状态记录）=====
def _today_str() -> str:
    """返回今天的日期字符串（YYYY.M.D 格式，与存档目录一致）。"""
    from datetime import date as _date
    d = _date.today()
    return f"{d.year}.{d.month}.{d.day}"


def load_snapshots() -> dict:
    """读取 data/snapshots.json，返回 {date_str: snapshot_dict}。"""
    if not SNAPSHOTS_PATH.exists():
        return {}
    try:
        with open(SNAPSHOTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_snapshots(snapshots: dict) -> None:
    try:
        with open(SNAPSHOTS_PATH, "w", encoding="utf-8") as f:
            json.dump(snapshots, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def generate_snapshot(target_date: str | None = None) -> dict:
    """为指定日期生成/更新快照。

    扫描该日的 articles.json + funds.json，统计：
      - 是否有拉取记录
      - 论文总数 / 公众号数 / 期刊数
      - 基金数
      - 涉及的来源列表（公众号名、期刊名）
      - 基金关键词

    target_date: None 表示今天，否则用 "YYYY.M.D" 格式。
    返回生成的快照字典。
    """
    if target_date is None:
        target_date = _today_str()

    day_dir = ARCHIVE_DIR / target_date
    jp = day_dir / "articles.json" if day_dir.is_dir() else None

    snap = {
        "date": target_date,
        "fetched": False,
        "total_articles": 0,
        "mp_count": 0,
        "journal_count": 0,
        "fund_count": 0,
        "mp_sources": [],
        "journal_sources": [],
        "fund_keywords": [],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    # ---- 统计论文 ----
    if jp and jp.exists():
        try:
            arts = json.load(open(jp, "r", encoding="utf-8"))
        except Exception:
            arts = []
        snap["fetched"] = True
        mp_set: set[str] = set()
        jnl_set: set[str] = set()
        mp_c, jnl_c = 0, 0
        for a in arts:
            cat = a.get("category", "")
            name = a.get("account", "未知")
            if cat == "期刊":
                jnl_c += 1
                jnl_set.add(name)
            else:  # 公众号 或未分类
                mp_c += 1
                mp_set.add(name)
        snap["total_articles"] = len(arts)
        snap["mp_count"] = mp_c
        snap["journal_count"] = jnl_c
        snap["mp_sources"] = sorted(mp_set)
        snap["journal_sources"] = sorted(jnl_set)

    # ---- 统计基金（funds.json 的 generated_at 可能跨天，以快照日期为准）----
    if FUNDS_PATH.exists():
        try:
            with open(FUNDS_PATH, "r", encoding="utf-8") as f:
                fdata = json.load(f)
            funds = fdata.get("funds", [])
            # 只在「今天」的快照里计入基金（避免历史快照重复计数）
            if target_date == _today_str() and funds:
                snap["fund_count"] = len(funds)
                kw_set = {k for x in funds for k in (x.get("hit_keywords") or [])}
                snap["fund_keywords"] = sorted(kw_set)
        except Exception:
            pass

    # 持久化
    snapshots = load_snapshots()
    snapshots[target_date] = snap
    save_snapshots(snapshots)
    return snap


def article_uid(a: dict) -> str:
    """文章稳定唯一标识：优先 url，否则 account|date|title 哈希。"""
    raw = a.get("url") or a.get("link") or ""
    if not raw:
        raw = "|".join([str(a.get("account", "")), str(a.get("date", "")), str(a.get("title", ""))])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def fund_uid(f: dict) -> str:
    """基金稳定唯一标识：优先 id（kd.nsfc 项目号），回退批准号/名称。"""
    return str(f.get("id") or f.get("ratify_no") or f.get("project_name", ""))


def get_accounts() -> list[dict]:
    """汇总所有来源（公众号 + 期刊）：合并配置白名单 + 期刊清单 + 本地存档。

    - 配置中的源（无论有无归档）都会列出，便于在导航里常驻
    - 每个源带 category 字段（公众号 / 期刊）
    - 旧存档文章若无 category，按白名单/期刊映射回退为「公众号」
    """
    cfg = load_config()
    whitelist = cfg.get("wewe_rss", {}).get("feeds", [])
    whitelist_map = {f["name"]: f.get("category", "公众号") for f in whitelist if f.get("name")}
    journals = load_journals_config()
    journal_map = {j["name"]: "期刊" for j in journals}

    sources: dict[str, dict] = {}
    for name, cat in whitelist_map.items():
        sources[name] = {"name": name, "category": cat}
    for name in journal_map:
        if name not in sources:
            sources[name] = {"name": name, "category": "期刊"}

    archive = scan_archive()
    counts: dict[str, dict] = {}
    for date_str, articles in archive.items():
        for a in articles:
            name = a.get("account") or "未知源"
            cat = (a.get("category")
                   or whitelist_map.get(name) or journal_map.get(name) or "公众号")
            if name not in counts:
                counts[name] = {"article_count": 0, "dates": set(), "category": cat}
            counts[name]["article_count"] += 1
            counts[name]["dates"].add(date_str)
            counts[name]["category"] = cat

    result = []
    # 公众号按白名单顺序
    for idx, name in enumerate(whitelist_map):
        src = sources[name]
        c = counts.get(name, {"article_count": 0, "dates": set(), "category": src["category"]})
        dates = sorted(c["dates"], key=_date_key, reverse=True)
        result.append({
            "name": name,
            "category": c["category"],
            "article_count": c["article_count"],
            "day_count": len(dates),
            "last_date": dates[0] if dates else None,
            "dates": dates,
            "configured": True,
            "_order": idx,
        })
    # 期刊按 journals.json 配置顺序
    for idx, j in enumerate(journals):
        name = j["name"]
        if name in sources and name not in {r["name"] for r in result}:
            c = counts.get(name, {"article_count": 0, "dates": set(), "category": "期刊"})
            dates = sorted(c["dates"], key=_date_key, reverse=True)
            result.append({
                "name": name,
                "category": c["category"],
                "article_count": c["article_count"],
                "day_count": len(dates),
                "last_date": dates[0] if dates else None,
                "dates": dates,
                "configured": True,
                "_order": idx + 1000,  # 期刊在公众号之后
            })
    # 存档中但不在配置里的（未知源），也列出
    for name, c in counts.items():
        if name not in sources:
            dates = sorted(c["dates"], key=_date_key, reverse=True)
            result.append({
                "name": name, "category": c["category"],
                "article_count": c["article_count"], "day_count": len(dates),
                "last_date": dates[0] if dates else None, "dates": dates,
                "configured": False,
                "_order": 9999,
            })

    cat_order = {"公众号": 0, "期刊": 1, "基金": 2}
    result.sort(key=lambda x: (cat_order.get(x["category"], 9), x.get("_order", 9999)))
    return result


def fetch_articles(account: str | None = None, category: str | None = None,
                   page: int = 1, size: int = 10) -> dict:
    """返回文章列表（跨日期，按日期倒序），可按来源/分类筛选 + 分页。"""
    archive = scan_archive()
    flat: list[dict] = []
    for date_str, articles in archive.items():
        for a in articles:
            item = dict(a)
            item["date"] = date_str
            item["category"] = a.get("category") or "公众号"
            flat.append(item)

    if account:
        flat = [a for a in flat if (a.get("account") or "未知源") == account]
    if category:
        flat = [a for a in flat if a["category"] == category]

    total = len(flat)
    start = (page - 1) * size
    end = start + size
    page_items = flat[start:end]

    return {
        "articles": page_items,
        "page": page,
        "size": size,
        "total": total,
        "has_more": end < total,
        "total_pages": (total + size - 1) // size if total else 0,
    }


def load_funds(q: str | None = None, kw: str | None = None, cat: str | None = None) -> dict:
    """读取 data/funds.json（fetch_funds.py 产出），支持按关键词/分类/全文检索过滤。"""
    if not FUNDS_PATH.exists():
        return {"funds": [], "generated_at": None, "completion_count": 0,
                "support_count": 0, "support_note": "", "keywords": [], "total": 0, "papers_total": 0}
    try:
        with open(FUNDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"funds": [], "generated_at": None, "completion_count": 0,
                "support_count": 0, "support_note": "", "keywords": [], "total": 0, "papers_total": 0}
    funds = data.get("funds", [])
    # 过滤已标记删除的基金
    deleted_f = set(load_deleted().get("funds", []))
    funds = [x for x in funds if fund_uid(x) not in deleted_f]
    if cat:
        funds = [x for x in funds if x.get("category") == cat]
    if kw:
        funds = [x for x in funds if kw in (x.get("hit_keywords") or [])]
    if q:
        q = q.lower()
        funds = [x for x in funds if q in (
            x.get("project_name", "") + x.get("keywords", "") + x.get("project_admin", "")
            + x.get("depend_unit", "") + x.get("code", "")
        ).lower()]
    # 确保每个基金带稳定 id
    for x in funds:
        if not x.get("id"):
            x["id"] = fund_uid(x)
    return {
        "funds": funds,
        "generated_at": data.get("generated_at"),
        "source": data.get("source"),
        "completion_count": data.get("completion_count", 0),
        "support_count": data.get("support_count", 0),
        "support_note": data.get("support_note", ""),
        "keywords": sorted({k for x in data.get("funds", []) for k in x.get("hit_keywords", [])}),
        "total": len(funds),
        "papers_total": sum(len(x.get("papers", [])) for x in data.get("funds", [])),
    }


def translate_fund_papers() -> dict:
    """翻译 funds.json 中所有成果论文的英文标题，写入 title_zh 字段并保存。

    使用 scripts/translator.py 的 translate_title（Google Translate + JSON 缓存）。
    """
    if not FUNDS_PATH.exists():
        return {"ok": False, "error": "funds.json 不存在，请先抓取基金数据", "translated": 0}
    try:
        with open(FUNDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"ok": False, "error": f"读取失败: {e}", "translated": 0}

    # 动态导入 translator
    import sys
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from translator import translate_title, _save_cache
    except ImportError as e:
        return {"ok": False, "error": f"导入翻译模块失败: {e}（需安装 deep_translator）", "translated": 0}

    funds = data.get("funds", [])
    total_papers = 0
    translated_count = 0
    for fund in funds:
        papers = fund.get("papers", [])
        for paper in papers:
            title = paper.get("title", "")
            if not title:
                continue
            total_papers += 1
            # 已有翻译则跳过
            if paper.get("title_zh"):
                translated_count += 1
                continue
            try:
                zh = translate_title(title)
                if zh and zh != title:
                    paper["title_zh"] = zh
                else:
                    paper["title_zh"] = title  # 翻译失败/无需翻译时保留原文
                translated_count += 1
            except Exception:
                paper["title_zh"] = title
                translated_count += 1

    # 保存回 funds.json
    try:
        with open(FUNDS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 同时保存翻译缓存
        try: _save_cache()
        except Exception: pass
    except Exception as e:
        return {"ok": False, "error": f"保存失败: {e}", "translated": translated_count}

    return {
        "ok": True,
        "translated": translated_count,
        "total_papers": total_papers,
        "message": f"已翻译 {translated_count}/{total_papers} 篇论文标题",
    }


# ===== NSFC 获批/资助查询代理（需验证码，用户手动输入）=====

_NSFC_BASE = "http://output.nsfc.gov.cn"
_NSFC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _nsfc_get(url: str) -> tuple[int, bytes, dict]:
    """GET 请求 NSFC 门户，返回 (status, body, response_headers)。"""
    req = urllib.request.Request(url, headers=_NSFC_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as r:
            return r.status, r.read(), dict(r.getheaders())
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b"", {}
    except Exception as e:
        return 0, str(e).encode("utf-8"), {}


def _nsfc_post(url: str, data: bytes, extra_headers: dict | None = None) -> tuple[int, bytes, dict]:
    """POST 请求 NSFC 门户。"""
    h = dict(_NSFC_HEADERS)
    h["Content-Type"] = "application/x-www-form-urlencoded"
    if extra_headers:
        h.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as r:
            return r.status, r.read(), dict(r.getheaders())
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b"", {}
    except Exception as e:
        return 0, str(e).encode("utf-8"), {}


def nsfc_captcha() -> dict:
    """获取国自然验证码图片（代理 output.nsfc.gov.cn）。

    返回 {"ok": bool, "image": base64|None, "cookies": dict, "error": str|None}
    """
    # 尝试多个可能的验证码 URL
    captcha_urls = [
        f"{_NSFC_BASE}/validateCode.jsp",
        f"{_NSFC_BASE}/validateCode",
        f"{_NSFC_BASE}/code.jsp",
    ]
    for url in captcha_urls:
        status, body, headers = _nsfc_get(url)
        ct = headers.get("Content-Type", "")
        if status == 200 and len(body) > 100 and ("image" in ct or not body.startswith(b"{")):
            import base64
            return {
                "ok": True,
                "image": base64.b64encode(body).decode("ascii"),
                "content_type": ct or "image/png",
                "url_used": url,
                "error": None,
            }
    # 如果都失败，返回错误信息
    return {"ok": False, "image": None, "error": f"无法获取验证码（HTTP {status}），请确认网络可访问 output.nsfc.gov.cn"}


def nsfc_support_query(params: dict) -> dict:
    """提交获批/资助项目查询（带验证码）。

    params: {captcha: str, keyword: str, year_start: str, year_end: str,
             person: str, unit: str, code: str, project_no: str}
    """
    import re
    from html.parser import HTMLParser

    captcha = params.get("captcha", "").strip()
    if not captcha:
        return {"ok": False, "results": [], "total": 0, "error": "请输入验证码"}

    # 构造查询参数（基于 output.nsfc.gov.cn projectQuery 表单字段）
    form_data = urllib.parse.urlencode({
        "keyword": params.get("keyword", ""),
        "personName": params.get("person", ""),
        "orgName": params.get("unit", ""),
        "projectNo": params.get("project_no", ""),
        "applyCode": params.get("code", ""),
        "startTime": params.get("year_start", "2020"),
        "endTime": params.get("year_end", "2025"),
        "validateCode": captcha,
        "resultNum": "50",
    }).encode()

    status, body, headers = _nsfc_post(f"{_NSFC_BASE}/projectQuery", form_data)

    if status != 200:
        return {"ok": False, "results": [], "total": 0, "error": f"查询请求失败（HTTP {status}）"}

    html = body.decode("utf-8", errors="ignore")

    # 检查是否提示验证码错误
    if "验证码" in html and ("错误" in html or "不正确" in html or "失效" in html):
        return {"ok": False, "results": [], "total": 0, "error": "验证码错误或已过期，请刷新重试"}

    # 解析结果表格
    results = _parse_nsfc_results(html)
    return {
        "ok": True,
        "results": results,
        "total": len(results),
        "raw_html_len": len(html),
        "error": None,
    }


def _parse_nsfc_results(html: str) -> list[dict]:
    """从 NSFC projectQuery 结果页面提取项目列表。"""
    import re

    results = []
    # 策略1：找包含"负责人"的表格数据行
    # NSFC 结果通常在 table 里，每行是一个项目
    tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.S | re.I)

    for table in tables:
        if "负责人" not in table and "依托单位" not in table:
            continue
        # 提取所有行
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S | re.I)
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
            clean = lambda s: re.sub(r"<[^>]+>", "", s).strip()
            cells = [clean(c) for c in cells]
            # 有效数据行：至少有 3 个单元格且包含中文内容
            if len(cells) >= 4 and any(re.search(r"[\u4e00-\u9fff]", c) for c in cells[:4]):
                item = {
                    "project_name": cells[0] if len(cells) > 0 else "",
                    "admin": cells[1] if len(cells) > 1 else "",
                    "unit": cells[2] if len(cells) > 2 else "",
                    "amount": cells[3] if len(cells) > 3 else "",
                    "year": cells[4] if len(cells) > 4 else "",
                    "type": cells[5] if len(cells) > 5 else "",
                    "code": cells[6] if len(cells) > 6 else "",
                    "no": cells[7] if len(cells) > 7 else "",
                }
                # 只保留看起来像真实数据的行（项目名长度合理）
                if len(item["project_name"]) >= 4:
                    results.append(item)

    # 去重（按项目名）
    seen = set()
    unique = []
    for r in results:
        key = r["project_name"]
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


# ===== /NSFC 代理结束 =====


def fetch_dates(account: str | None = None) -> list[dict]:
    """返回按日期分组的文章数（供历史浏览）。"""
    archive = scan_archive()
    result = []
    for date_str, articles in archive.items():
        filtered = articles
        if account:
            filtered = [a for a in articles if (a.get("account") or "未知公众号") == account]
        if filtered:
            result.append({"date": date_str, "count": len(filtered)})
    return result


def start_fetch(start_date: str | None = None, end_date: str | None = None) -> None:
    """后台跑 daily.py，实现抓取。

    start_date/end_date 都为 None：现场抓取今天（--force）
    有日期：抓取 [start_date, end_date] 闭区间（--start/--end）
    """
    global FETCH_STATE
    with FETCH_LOCK:
        if FETCH_STATE["running"]:
            return
        FETCH_STATE.update(running=True, startedAt=now_iso(), finishedAt=None, output="", code=None)

    cmd = [str(PYTHON_EXE), str(DAILY_PY), "--force"]
    if start_date and end_date:
        cmd += ["--start", start_date, "--end", end_date]

    def worker():
        global FETCH_STATE
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True, text=True, encoding="utf-8", timeout=600,
                cwd=str(SCRIPTS_DIR),
            )
            with FETCH_LOCK:
                FETCH_STATE.update(
                    running=False,
                    finishedAt=now_iso(),
                    output=(proc.stdout or "") + (proc.stderr or ""),
                    code=proc.returncode,
                )
                # 抓取完成后自动生成/更新当日快照
                try: generate_snapshot()
                except Exception: pass
        except Exception as e:
            with FETCH_LOCK:
                FETCH_STATE.update(running=False, finishedAt=now_iso(), output=str(e), code=-1)

    threading.Thread(target=worker, daemon=True).start()


def start_funds_fetch() -> None:
    """后台运行 fetch_funds.py 抓取国自然基金数据。"""
    global FUNDS_FETCH_STATE
    with FUNDS_FETCH_LOCK:
        if FUNDS_FETCH_STATE["running"]:
            return
        FUNDS_FETCH_STATE.update(running=True, startedAt=now_iso(), finishedAt=None, output="", code=None)

    cmd = [str(PYTHON_EXE), str(SCRIPTS_DIR / "fetch_funds.py")]

    def worker():
        global FUNDS_FETCH_STATE
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True, text=True, encoding="utf-8", timeout=900,
                cwd=str(SCRIPTS_DIR),
            )
            with FUNDS_FETCH_LOCK:
                FUNDS_FETCH_STATE.update(
                    running=False,
                    finishedAt=now_iso(),
                    output=(proc.stdout or "") + (proc.stderr or ""),
                    code=proc.returncode,
                )
        except Exception as e:
            with FUNDS_FETCH_LOCK:
                FUNDS_FETCH_STATE.update(running=False, finishedAt=now_iso(), output=str(e), code=-1)

    threading.Thread(target=worker, daemon=True).start()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    """从 POST 请求体读取 JSON，失败返回空 dict。"""
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    try:
        return json.loads(handler.rfile.read(length).decode("utf-8") or "{}")
    except Exception:
        return {}


def json_response(handler: BaseHTTPRequestHandler, payload, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def static_response(handler: BaseHTTPRequestHandler, filename: str) -> None:
    """serve web 目录下的静态文件。"""
    path = APP_DIR / filename
    if not path.exists():
        handler.send_error(404, "Not Found")
        return
    content_type = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
    }.get(path.suffix, "application/octet-stream")
    body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默日志，避免刷屏

    def _send_error(self, status, message):
        json_response(self, {"error": message}, status)

    def do_OPTIONS(self):
        # 允许跨域预检（file:// 双击打开 html 时需要）
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            if path in ("/", "/index.html"):
                static_response(self, "paper_observatory.html")
            elif path == "/paper_observatory.css":
                static_response(self, "paper_observatory.css")
            elif path == "/paper_observatory.js":
                static_response(self, "paper_observatory.js")
            elif path == "/api/health":
                reload_paths()
                json_response(self, {"ok": True, "archive": str(ARCHIVE_DIR)})
            elif path == "/api/overview":
                reload_paths()
                accounts = get_accounts()
                total_articles = sum(a["article_count"] for a in accounts)
                total_days = len(scan_archive())
                # 按分类汇总
                categories: dict[str, dict] = {}
                for a in accounts:
                    cat = a["category"]
                    bucket = categories.setdefault(cat, {"sources": 0, "articles": 0, "days": 0})
                    bucket["sources"] += 1
                    bucket["articles"] += a["article_count"]
                    bucket["days"] = max(bucket["days"], a["day_count"])
                json_response(self, {
                    "accounts": accounts,
                    "categories": categories,
                    "total_articles": total_articles,
                    "total_accounts": len(accounts),
                    "total_days": total_days,
                })
            elif path == "/api/accounts":
                reload_paths()
                json_response(self, {"accounts": get_accounts()})
            elif path == "/api/articles":
                reload_paths()
                account = (qs.get("account") or [None])[0]
                category = (qs.get("category") or [None])[0]
                page = int((qs.get("page") or ["1"])[0])
                size = int((qs.get("size") or ["10"])[0])
                json_response(self, fetch_articles(account, category, page, size))
            elif path == "/api/dates":
                reload_paths()
                account = (qs.get("account") or [None])[0]
                json_response(self, {"dates": fetch_dates(account)})
            elif path == "/api/funds":
                reload_paths()
                q = (qs.get("q") or [None])[0]
                kw = (qs.get("kw") or [None])[0]
                cat = (qs.get("cat") or [None])[0]
                json_response(self, load_funds(q, kw, cat))
            elif path == "/api/funds/captcha":
                # 代理获取国自然验证码图片
                result = nsfc_captcha()
                json_response(self, result)
            elif path == "/api/funds/fetch/status":
                json_response(self, FUNDS_FETCH_STATE)
            elif path == "/api/fetch/status":
                json_response(self, FETCH_STATE)
            elif path == "/api/snapshots":
                # 列出所有快照日期（倒序）
                snaps = load_snapshots()
                dates = sorted(snaps.keys(), key=lambda d: _date_key(d), reverse=True)
                json_response(self, {"dates": dates, "total": len(dates)})
            elif path == "/api/deletion-audit":
                audit_date = (qs.get("date") or [None])[0]
                json_response(self, deletion_audit_summary(audit_date))
            elif path.startswith("/api/snapshots/"):
                # 获取某日快照详情
                snap_date = path[len("/api/snapshots/"):]
                snaps = load_snapshots()
                if snap_date in snaps:
                    json_response(self, snaps[snap_date])
                else:
                    # 日期不存在则尝试实时生成
                    try:
                        snap = generate_snapshot(snap_date)
                        json_response(self, snap)
                    except Exception as e:
                        self._send_error(404, f"无 {snap_date} 的快照记录")
            else:
                self._send_error(404, "Not Found")
        except Exception as e:
            self._send_error(500, str(e))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/fetch":
            start_fetch()
            json_response(self, {"started": True, "message": "现场抓取已启动"})
        elif path == "/api/fetch-custom":
            # 读取 JSON body 中的 start_date / end_date（YYYY-MM-DD）
            start_date = None
            end_date = None
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 0:
                    body = self.rfile.read(length).decode("utf-8")
                    payload = json.loads(body)
                    start_date = (payload.get("start_date") or "").strip() or None
                    end_date = (payload.get("end_date") or "").strip() or None
            except Exception:
                start_date = end_date = None
            if not start_date or not end_date:
                self._send_error(400, "缺少 start_date / end_date 参数")
                return
            start_fetch(start_date=start_date, end_date=end_date)
            json_response(self, {"started": True, "message": f"自定义抓取已启动（{start_date} ~ {end_date}）"})
        elif path == "/api/funds/support-query":
            # 获批/资助项目查询（带验证码）
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                params = json.loads(body)
            except Exception:
                params = {}
            result = nsfc_support_query(params)
            json_response(self, result)
        elif path == "/api/funds/fetch":
            start_funds_fetch()
            json_response(self, {"started": True, "message": "国自然基金抓取已启动，请稍候…"})
        elif path == "/api/funds/translate":
            # 翻译基金成果论文的英文标题为中文
            result = translate_fund_papers()
            json_response(self, result)
        elif path == "/api/articles/delete":
            # 标记删除文章（按 id 加入 data/deleted.json 索引，非物理删除）
            body = _read_json_body(self)
            ids = body.get("ids", [])
            d = load_deleted()
            existing = set(d.get("articles", []))
            added = 0
            added_ids = []
            for i in ids:
                if i and i not in existing:
                    existing.add(i)
                    added += 1
                    added_ids.append(i)
            d["articles"] = list(existing)
            save_deleted(d)
            record_deletions("article", added_ids, body.get("records", []))
            json_response(self, {"ok": True, "deleted": added, "message": f"已删除 {added} 篇文章"})
        elif path == "/api/funds/delete":
            # 标记删除基金（按 id 加入索引）
            body = _read_json_body(self)
            ids = body.get("ids", [])
            d = load_deleted()
            existing = set(d.get("funds", []))
            added = 0
            added_ids = []
            for i in ids:
                if i and i not in existing:
                    existing.add(i)
                    added += 1
                    added_ids.append(i)
            d["funds"] = list(existing)
            save_deleted(d)
            record_deletions("fund", added_ids, body.get("records", []))
            json_response(self, {"ok": True, "deleted": added, "message": f"已删除 {added} 个基金"})
        elif path == "/api/deleted/clear":
            # 恢复全部已删除项（清空索引）
            save_deleted({"articles": [], "funds": []})
            json_response(self, {"ok": True, "message": "已恢复全部删除项"})
        elif path == "/api/snapshots/generate":
            # 手动生成/更新今日快照
            body = _read_json_body(self)
            target = body.get("date")  # 可选，默认今天
            snap = generate_snapshot(target)
            json_response(self, {"ok": True, "snapshot": snap})
        else:
            self._send_error(404, "Not Found")


def main():
    parser = argparse.ArgumentParser(description="论文观察台")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8032)
    args = parser.parse_args()

    reload_paths()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Paper Observatory running at http://127.0.0.1:{args.port}")
    print(f"Archive dir: {ARCHIVE_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

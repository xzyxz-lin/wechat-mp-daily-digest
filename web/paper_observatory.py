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
import json
import subprocess
import threading
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


def scan_archive() -> dict:
    """扫描存档目录，返回 {date_str: [articles]}（日期倒序）。"""
    result: dict = {}
    if not ARCHIVE_DIR.is_dir():
        return result
    for day_dir in ARCHIVE_DIR.iterdir():
        if not day_dir.is_dir():
            continue
        jp = day_dir / "articles.json"
        if jp.exists():
            try:
                with open(jp, "r", encoding="utf-8") as f:
                    result[day_dir.name] = json.load(f)
            except Exception:
                result[day_dir.name] = []
    return dict(sorted(result.items(), key=lambda kv: _date_key(kv[0]), reverse=True))


def _date_key(date_str: str) -> str:
    """把 2026.8.13 归一化为可排序的 2026-08-13。"""
    parts = date_str.split(".")
    if len(parts) == 3:
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return date_str


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
        except Exception as e:
            with FETCH_LOCK:
                FETCH_STATE.update(running=False, finishedAt=now_iso(), output=str(e), code=-1)

    threading.Thread(target=worker, daemon=True).start()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
            elif path == "/api/fetch/status":
                json_response(self, FETCH_STATE)
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

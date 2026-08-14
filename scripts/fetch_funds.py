#!/usr/bin/env python3
"""
fetch_funds.py —— 国自然基金（结题 + 成果论文）抓取脚本。

数据源：国家自然科学基金大数据知识管理服务门户  https://kd.nsfc.cn/
  - 结题项目检索：  POST /api/baseQuery/completionQueryResultsData
  - 结题项目详情：  POST /api/baseQuery/conclusionProjectInfo/{id}  （含成果论文 resultsList）
  - 资助/获批检索：  POST /api/baseQuery/supportQueryResultsData  （需图形验证码，best-effort）

关键说明：
  1. 结题项目检索返回的响应体是「base64 编码的 DES 密文」，需用密钥 "IFROMC86"、DES/ECB/Pkcs7 解密。
  2. 结题项目详情接口返回的是明文 JSON（无需解密）。
  3. 资助/获批检索接口需要图形验证码，自动化无法破解，脚本会 best-effort 尝试，
     遇到验证码错误时跳过并在日志中提示（结题模块不受影响）。

输出：
  data/funds.json            结构化数据（观察台后端 /api/funds 读取）
  data/funds.html            本地可视化报告
  data/funds.md              本地 Markdown 报告

用法：
  python fetch_funds.py                       # 按 config.json 的 funds 配置抓取
  python fetch_funds.py --keywords 膜 反渗透  # 覆盖关键词
  python fetch_funds.py --years 2024 2023     # 覆盖结题年度
  python fetch_funds.py --max 30 --no-papers  # 每关键词最多30条、不抓详情论文
  python fetch_funds.py --dry-run             # 只测连通性，不落盘
"""
from __future__ import annotations

import argparse
import base64
import json
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime

try:
    from Crypto.Cipher import DES
except ImportError:
    raise SystemExit("缺少依赖 pycryptodome，请运行：pip install pycryptodome")

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_DIR / "config" / "config.json"
DATA_DIR = PROJECT_DIR / "data"
FUNDS_JSON = DATA_DIR / "funds.json"
FUNDS_HTML = DATA_DIR / "funds.html"
FUNDS_MD = DATA_DIR / "funds.md"

BASE_URL = "https://kd.nsfc.cn"
API = BASE_URL + "/api"

# DES 解密密钥（来自 kd.nsfc.cn 前端 JS：p.a.enc.Utf8.parse("IFROMC86")）
_DES_KEY = b"IFROMC86"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": BASE_URL + "/",
    "X-Requested-With": "XMLHttpRequest",
}

# 默认研究方向关键词（覆盖：膜 / 反渗透 / 膜污染清洗 / CFD 流场）
DEFAULT_KEYWORDS = ["膜", "反渗透", "膜污染", "膜清洗", "CFD", "流场"]
DEFAULT_YEARS = ["2024", "2023", "2022"]

_REQUEST_INTERVAL = 1.3  # 两次请求间隔（秒），避免 503 限流
_last_req = 0.0


def _des_decrypt(cipher_b64: str) -> str:
    """DES/ECB/Pkcs7 解密 kd.nsfc.cn 返回的密文。"""
    ct = base64.b64decode(cipher_b64)
    cipher = DES.new(_DES_KEY, DES.MODE_ECB)
    pt = cipher.decrypt(ct)
    pad = pt[-1]
    if 1 <= pad <= 8:
        pt = pt[:-pad]
    return pt.decode("utf-8", "ignore")


def _request(path: str, body: dict | None = None, retries: int = 4) -> dict:
    """POST 到 kd.nsfc.cn API，自动处理「密文响应」与「明文响应」。
    遇到 503 限流时指数退避重试。"""
    global _last_req
    for attempt in range(retries + 1):
        now = time.time()
        wait = _REQUEST_INTERVAL - (now - _last_req)
        if wait > 0:
            time.sleep(wait)
        _last_req = time.time()

        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(API + path, data=data, headers=_HEADERS, method="POST")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
                raw = r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < retries:
                backoff = 2 ** (attempt + 1)
                print(f"    [限流 503] {path} 第{attempt+1}次重试，等待 {backoff}s…")
                time.sleep(backoff)
                continue
            return {"_error": f"HTTP {e.code}", "_raw": e.read().decode("utf-8", "ignore")[:300]}
        except Exception as e:  # noqa: BLE001
            if attempt < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            return {"_error": str(e)[:200]}

        # 尝试 JSON 解析；失败则当作密文解密
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            try:
                plain = _des_decrypt(raw)
                return json.loads(plain)
            except Exception:  # noqa: BLE001
                if attempt < retries:
                    time.sleep(2)
                    continue
                return {"_error": "无法解析响应（可能需验证码或限流）", "_raw": raw[:200]}
    return {"_error": "重试耗尽"}


def _build_completion_body(keyword: str, conclusion_year: str, page: int, page_size: int) -> dict:
    return {
        "code": "", "fuzzyKeyword": "", "complete": True, "isFuzzySearch": False,
        "conclusionYear": conclusion_year, "dependUnit": "", "keywords": "",
        "pageNum": page, "pageSize": page_size, "personInCharge": "",
        "projectName": keyword, "projectType": "", "subPType": "", "psPType": "",
        "ratifyNo": "", "ratifyYear": "", "order": "enddate", "ordering": "desc",
        "codeScreening": "", "dependUnitScreening": "", "keywordsScreening": "",
        "projectTypeNameScreening": "",
    }


def query_completion(keyword: str, conclusion_year: str, page: int = 1, page_size: int = 20):
    """返回 (rows, has_more)。rows 为原始数组列表。"""
    resp = _request("/baseQuery/completionQueryResultsData",
                    _build_completion_body(keyword, conclusion_year, page, page_size))
    if "_error" in resp:
        print(f"  [结题检索] 关键词={keyword} 年度={conclusion_year} 页={page} 失败：{resp['_error']}")
        return [], False
    if resp.get("code") != 200:
        print(f"  [结题检索] 关键词={keyword} 年度={conclusion_year} 页={page} 返回：{resp.get('message')}")
        return [], False
    data = resp.get("data") or {}
    rows = data.get("resultsData") or []
    return rows, len(rows) >= page_size


def parse_completion_row(row: list) -> dict:
    """把结题检索的一行解析为基金项目字典。"""
    # 列索引（已实测）：
    # 0 id,1 名称,2 批准号,3 类型,4 单位,5 负责人,6 金额(万),7 批准年度,
    # 8 关键词,9 ?,10 成果计数"a;b;c;d;e",11 ?,12 ?,13 ?,14 申请代码,15 结题年度,16-18 ''
    def g(i):
        return row[i] if i < len(row) else ""

    result_counts = g(10)
    paper_count = 0
    if result_counts:
        parts = result_counts.split(";")
        if parts and parts[0].isdigit():
            paper_count = int(parts[0])

    return {
        "id": g(0),
        "project_name": g(1),
        "ratify_no": g(2),
        "project_type": g(3),
        "depend_unit": g(4),
        "project_admin": g(5),
        "support_num": g(6),
        "ratify_year": g(7),
        "keywords": g(8),
        "paper_count": paper_count,
        "code": g(14),
        "conclusion_year": g(15),
    }


def get_conclusion_detail(pid: str) -> dict | None:
    """结题项目详情（明文 JSON），含成果论文 resultsList。"""
    resp = _request(f"/baseQuery/conclusionProjectInfo/{pid}")
    if "_error" in resp:
        return None
    if resp.get("code") != 200:
        return None
    return resp.get("data")


def parse_results(results_list: list) -> list[dict]:
    """resultsList -> 论文列表。每个元素形如 {"result":[序号,id,标题,类型,作者,flag]}。"""
    papers = []
    for item in results_list or []:
        arr = item.get("result") if isinstance(item, dict) else None
        if not arr or len(arr) < 5:
            continue
        # arr: [idx, result_id, title, type, authors, flag]
        papers.append({
            "result_id": arr[1],
            "title": arr[2],
            "type": arr[3],
            "authors": arr[4],
        })
    return papers


def query_support(keyword: str, ratify_year: str) -> list[dict]:
    """资助/获批检索（best-effort，需验证码，失败返回空）。"""
    body = _build_completion_body(keyword, "", 1, 20)
    body["ratifyYear"] = ratify_year
    resp = _request("/baseQuery/supportQueryResultsData", body, retries=0)
    if "_error" in resp:
        print(f"  [获批检索] 关键词={keyword} 年度={ratify_year} 失败（可能需验证码）：{resp['_error']}")
        return []
    if resp.get("code") != 200:
        print(f"  [获批检索] 关键词={keyword} 年度={ratify_year} 跳过：{resp.get('message')}（需图形验证码，自动化无法破解）")
        return []
    data = resp.get("data") or {}
    rows = data.get("resultsData") or []
    out = []
    for row in rows:
        d = parse_completion_row(row)
        d["category"] = "support"
        out.append(d)
    return out


def relevance_score(fund: dict, keywords: list[str]) -> float:
    """关键词在项目名/关键词/摘要中的命中次数，作为相关性得分。"""
    text = " ".join([
        fund.get("project_name", ""),
        fund.get("keywords", ""),
        fund.get("abstract_c", ""),
    ]).lower()
    score = 0.0
    for kw in keywords:
        score += text.count(kw.lower()) * (2.0 if kw in fund.get("project_name", "").lower() else 1.0)
    return score


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def scrape(keywords: list[str], years: list[str], max_per_keyword: int,
           fetch_papers: bool, category: str = "completion") -> list[dict]:
    """抓取结题项目（主流程），按关键词×年度展开，去重并打分。"""
    seen: dict[str, dict] = {}  # ratify_no -> fund
    for kw in keywords:
        collected = 0
        for yr in years:
            if collected >= max_per_keyword:
                break
            page = 1
            while collected < max_per_keyword:
                rows, has_more = query_completion(kw, yr, page=page, page_size=20)
                if not rows:
                    break
                for row in rows:
                    fund = parse_completion_row(row)
                    if not fund.get("ratify_no"):
                        continue
                    rn = fund["ratify_no"]
                    if rn in seen:
                        # 同一项目命中多关键词：补充关键词标签
                        if kw not in seen[rn].get("hit_keywords", []):
                            seen[rn].setdefault("hit_keywords", []).append(kw)
                        continue
                    fund["category"] = category
                    fund["hit_keywords"] = [kw]
                    fund["conclusion_year"] = fund.get("conclusion_year") or yr
                    seen[rn] = fund
                    collected += 1
                    if collected >= max_per_keyword:
                        break
                if not has_more:
                    break
                page += 1
        print(f"  [关键词 {kw}] 已收集 {min(collected, max_per_keyword)} 条（累计去重 {len(seen)}）")
    return list(seen.values())


def enrich_details(funds: list[dict], fetch_papers: bool) -> None:
    """拉取每个项目的详情（摘要 + 成果论文）。"""
    total = len(funds)
    for i, fund in enumerate(funds, 1):
        if not fund.get("id"):
            continue
        try:
            det = get_conclusion_detail(fund["id"])
        except Exception:  # noqa: BLE001
            det = None
        if not det:
            continue
        fund["abstract_c"] = det.get("projectAbstractC", "")
        fund["abstract_e"] = det.get("projectAbstractE", "")
        fund["conclusion_abstract"] = det.get("conclusionAbstract", "")
        fund["keywords_c"] = det.get("projectKeywordC", "")
        fund["keywords_e"] = det.get("projectKeywordE", "")
        fund["research_scope"] = det.get("researchTimeScope", "")
        fund["participants"] = [p.get("name") for p in (det.get("participatantsList") or []) if isinstance(p, dict)]
        if fetch_papers:
            fund["papers"] = parse_results(det.get("resultsList"))
        if i % 10 == 0 or i == total:
            print(f"  [详情] {i}/{total} 完成（含论文 {len(fund.get('papers', []))} 篇）")
        time.sleep(_REQUEST_INTERVAL)


def save_outputs(funds: list[dict], support_funds: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "国家自然科学基金大数据知识管理服务门户 https://kd.nsfc.cn/",
        "completion_count": len(funds),
        "support_count": len(support_funds),
        "support_note": "获批/资助名单需图形验证码，自动化暂未抓取；结题项目已覆盖近年的同方向已结题基金。" if not support_funds else "",
        "funds": funds + support_funds,
    }
    with open(FUNDS_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    render_funds_html(payload, FUNDS_HTML)
    render_funds_md(payload, FUNDS_MD)
    print(f"已写出：{FUNDS_JSON.name} / {FUNDS_HTML.name} / {FUNDS_MD.name}")
    print(f"结题项目 {len(funds)} 条，获批项目 {len(support_funds)} 条")


# ===== 本地 HTML / MD 渲染 =====
def _esc(s: str) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_funds_html(payload: dict, out_path: Path) -> None:
    funds = payload["funds"]
    cards = []
    for f in sorted(funds, key=lambda x: x.get("relevance", 0), reverse=True):
        papers = f.get("papers", [])
        paper_html = ""
        if papers:
            items = "".join(
                f"<li><span class='ptype'>{_esc(p['type'])}</span> {_esc(p['title'])}"
                f"<br><small>{_esc(p['authors'])}</small></li>" for p in papers[:15]
            )
            paper_html = f"<div class='papers'><b>成果论文（{len(papers)} 篇，显示前 {min(15, len(papers))}）</b><ul>{items}</ul></div>"
        cards.append(f"""
        <div class="fund">
          <div class="fund__head">
            <h3>{_esc(f['project_name'])}</h3>
            <span class="tag">{_esc(f.get('project_type',''))}</span>
          </div>
          <div class="fund__meta">
            <span>负责人 {_esc(f.get('project_admin',''))}</span>
            <span>单位 {_esc(f.get('depend_unit',''))}</span>
            <span>批准号 {_esc(f.get('ratify_no',''))}</span>
            <span>年度 {_esc(f.get('ratify_year',''))}→结题 {_esc(f.get('conclusion_year',''))}</span>
            <span>金额 {_esc(f.get('support_num',''))} 万</span>
            <span>代码 {_esc(f.get('code',''))}</span>
          </div>
          <div class="fund__kw">关键词：{_esc(f.get('keywords') or f.get('keywords_c') or '')}</div>
          {paper_html}
        </div>""")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>国自然基金观察 · {payload['generated_at'][:10]}</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;max-width:920px;margin:24px auto;padding:0 20px;color:#222;background:#fafafa;line-height:1.6}}
h1{{border-bottom:2px solid #7a4fb5;padding-bottom:8px}}
.fund{{background:#fff;border-radius:10px;padding:16px 20px;margin:14px 0;box-shadow:0 1px 4px rgba(0,0,0,.06);border-left:4px solid #7a4fb5}}
.fund__head{{display:flex;justify-content:space-between;align-items:baseline;gap:12px}}
.fund__head h3{{margin:0;font-size:17px}}
.tag{{background:#efe6f9;color:#7a4fb5;padding:2px 8px;border-radius:6px;font-size:12px;white-space:nowrap}}
.fund__meta{{display:flex;flex-wrap:wrap;gap:6px 16px;margin:8px 0;font-size:13px;color:#555}}
.fund__kw{{font-size:13px;color:#666}}
.papers{{margin-top:10px;background:#faf7fe;border-radius:8px;padding:10px 14px}}
.papers b{{font-size:13px;color:#7a4fb5}}
.papers ul{{margin:6px 0 0;padding-left:18px}}
.papers li{{margin:4px 0;font-size:13.5px}}
.ptype{{background:#e3f0e8;color:#2f7d4f;padding:1px 6px;border-radius:4px;font-size:11px;margin-right:6px}}
small{{color:#888}}
</style></head><body>
<h1>国自然基金观察台 · 结题项目 + 成果论文</h1>
<p>生成时间 {_esc(payload['generated_at'])} ｜ 结题项目 {payload['completion_count']} 条 ｜ 获批项目 {payload['support_count']} 条</p>
<p><small>数据源：{_esc(payload['source'])}</small></p>
{''.join(cards)}
</body></html>"""
    out_path.write_text(html, encoding="utf-8")


def render_funds_md(payload: dict, out_path: Path) -> None:
    lines = [
        f"# 国自然基金观察台 · 结题项目 + 成果论文",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 结题项目：**{payload['completion_count']}** 条 ｜ 获批项目：**{payload['support_count']}** 条",
        f"- 数据源：{payload['source']}",
        "",
    ]
    for f in sorted(payload["funds"], key=lambda x: x.get("relevance", 0), reverse=True):
        lines.append(f"## {f.get('project_name','')}")
        lines.append("")
        lines.append(f"- **类型**：{f.get('project_type','')}")
        lines.append(f"- **负责人**：{f.get('project_admin','')} ｜ **单位**：{f.get('depend_unit','')}")
        lines.append(f"- **批准号**：{f.get('ratify_no','')} ｜ **年度**：{f.get('ratify_year','')}→结题 {f.get('conclusion_year','')}")
        lines.append(f"- **金额**：{f.get('support_num','')} 万 ｜ **申请代码**：{f.get('code','')}")
        lines.append(f"- **关键词**：{f.get('keywords') or f.get('keywords_c') or ''}")
        papers = f.get("papers", [])
        if papers:
            lines.append(f"- **成果论文（{len(papers)} 篇）**：")
            for p in papers[:15]:
                lines.append(f"  - [{p['type']}] {p['title']} — {p['authors']}")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    cfg = load_config().get("funds", {})
    ap = argparse.ArgumentParser(description="抓取国自然结题基金 + 成果论文")
    ap.add_argument("--keywords", nargs="*", default=None, help="覆盖关键词（默认读 config.json）")
    ap.add_argument("--years", nargs="*", default=None, help="覆盖结题年度")
    ap.add_argument("--max", type=int, default=None, help="每关键词最多条数")
    ap.add_argument("--no-papers", action="store_true", help="不抓取详情中的成果论文")
    ap.add_argument("--dry-run", action="store_true", help="只测连通性，不落盘")
    args = ap.parse_args()

    keywords = args.keywords or cfg.get("keywords") or DEFAULT_KEYWORDS
    years = args.years or cfg.get("conclusion_years") or DEFAULT_YEARS
    max_per = args.max or cfg.get("max_per_keyword") or 20
    fetch_papers = not args.no_papers and cfg.get("fetch_papers", True) is not False

    print(f"=== 国自然基金抓取 ===")
    print(f"关键词：{keywords}")
    print(f"结题年度：{years}")
    print(f"每关键词上限：{max_per} ｜ 抓论文：{fetch_papers}")

    # 连通性 + 解密自检
    test_rows, _ = query_completion(keywords[0], years[0], page=1, page_size=1)
    if not test_rows:
        print("⚠️ 连通性或解密自检失败，请检查网络 / 是否被限流。终止。")
        return
    print(f"✅ 连通 + DES 解密正常，样例项目：{parse_completion_row(test_rows[0])['project_name']}")

    if args.dry_run:
        print("dry-run 完成，未落盘。")
        return

    funds = scrape(keywords, years, max_per, fetch_papers)
    if fetch_papers:
        print(f"拉取 {len(funds)} 个项目的详情与论文…")
        enrich_details(funds, fetch_papers)

    # 相关性打分
    for f in funds:
        f["relevance"] = relevance_score(f, keywords)
    funds.sort(key=lambda x: x.get("relevance", 0), reverse=True)

    # best-effort 获批名单（遇验证码跳过）
    support_funds = []
    try:
        support_funds = query_support(keywords[0], years[0])
    except Exception as e:  # noqa: BLE001
        print(f"  [获批检索] 跳过：{e}")

    save_outputs(funds, support_funds)


if __name__ == "__main__":
    main()

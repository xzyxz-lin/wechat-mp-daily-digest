#!/usr/bin/env python3
"""
公众号论文观察台 - 本地 Web 管理后端（纯标准库，零依赖）。

仿照「Project Atlas 项目文件总控」的架构：BaseHTTPRequestHandler + ThreadingHTTPServer。

数据源：本地存档目录 A:\\研零课题\\研零课题资料\\每日推送\\每日论文推送\\YYYY.M.D\\articles.json

API：
  GET  /api/health          健康检查
  GET  /api/overview        总览（公众号汇总 + 全局统计）
  GET  /api/accounts        公众号列表
  GET  /api/articles        文章列表（?account=&page=&size=）
  GET  /api/dates           某公众号的日期列表（?account=）
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
SCRIPTS_DIR = PROJECT_DIR / "scripts"
PYTHON_EXE = SCRIPTS_DIR / ".venv" / "Scripts" / "python.exe"
DAILY_PY = SCRIPTS_DIR / "daily.py"

_config: dict = {}
ARCHIVE_DIR: Path = Path(".")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def reload_paths():
    global ARCHIVE_DIR
    _config = load_config()
    ARCHIVE_DIR = Path(_config["output"]["local_dir"])


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
    """汇总每个公众号的文章数、天数、最近日期。"""
    archive = scan_archive()
    accs: dict[str, dict] = {}
    for date_str, articles in archive.items():
        for a in articles:
            name = a.get("account") or "未知公众号"
            if name not in accs:
                accs[name] = {
                    "name": name,
                    "article_count": 0,
                    "dates": set(),
                }
            accs[name]["article_count"] += 1
            accs[name]["dates"].add(date_str)
    result = []
    for name, acc in accs.items():
        dates = sorted(acc["dates"], key=_date_key, reverse=True)
        result.append({
            "name": name,
            "article_count": acc["article_count"],
            "day_count": len(dates),
            "last_date": dates[0] if dates else None,
            "dates": dates,
        })
    result.sort(key=lambda x: x["article_count"], reverse=True)
    return result


def fetch_articles(account: str | None = None, page: int = 1, size: int = 10) -> dict:
    """返回文章列表（跨日期，按日期倒序），可按公众号筛选 + 分页。"""
    archive = scan_archive()
    flat: list[dict] = []
    for date_str, articles in archive.items():
        for a in articles:
            item = dict(a)
            item["date"] = date_str
            flat.append(item)

    if account:
        flat = [a for a in flat if (a.get("account") or "未知公众号") == account]

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


def start_fetch() -> None:
    """后台跑 daily.py --force，实现现场抓取。"""
    global FETCH_STATE
    with FETCH_LOCK:
        if FETCH_STATE["running"]:
            return
        FETCH_STATE.update(running=True, startedAt=now_iso(), finishedAt=None, output="", code=None)

    def worker():
        global FETCH_STATE
        try:
            proc = subprocess.run(
                [str(PYTHON_EXE), str(DAILY_PY), "--force"],
                capture_output=True, text=True, encoding="utf-8", timeout=300,
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
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默日志，避免刷屏

    def _send_error(self, status, message):
        json_response(self, {"error": message}, status)

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
                json_response(self, {
                    "accounts": accounts,
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
                page = int((qs.get("page") or ["1"])[0])
                size = int((qs.get("size") or ["10"])[0])
                json_response(self, fetch_articles(account, page, size))
            elif path == "/api/dates":
                reload_paths()
                account = (qs.get("account") or [None])[0]
                json_response(self, {"dates": fetch_dates(account)})
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
        else:
            self._send_error(404, "Not Found")


def main():
    parser = argparse.ArgumentParser(description="公众号论文观察台")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8031)
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

"""
从 WeWe RSS 拉取公众号文章。

适配 wewe-rss 实际输出格式：
  - 日期字段：date_modified (UTC ISO 8601, 末尾带 Z)
  - 作者字段：author = {"name": "公众号名"} (单个对象)
  - 内容：默认 content_html 为空 (需开启 FEED_MODE=fulltext 才有全文)
  - 每篇文章独立 id，没有"公众号 -> feed_id"的固定对应
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"
BEIJING = timezone(timedelta(hours=8))


def load_config(path=None):
    """加载配置文件。"""
    cfg_path = Path(path) if path else CONFIG_PATH
    if not cfg_path.exists():
        print(f"ERROR: 配置文件不存在: {cfg_path}")
        print("请先复制 config/config.example.json 为 config/config.json")
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_all(base_url, auth_code=None):
    """调用 WeWe RSS 的 /feeds/all.json 拉取所有文章。"""
    url = f"{base_url.rstrip('/')}/feeds/all.json"
    headers = {}
    if auth_code:
        headers["Authorization"] = f"Bearer {auth_code}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_date(s):
    """解析 ISO 8601 日期字符串（含 Z 后缀）。"""
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def filter_by_date(items, target_date):
    """过滤指定日期（北京时间）发布的文章。

    wewe-rss 的 date_modified 是 UTC 时间，转北京时间后比较日期。
    """
    result = []
    for item in items:
        pub = parse_date(item.get("date_modified") or item.get("date_published"))
        if not pub:
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=BEIJING)
        local = pub.astimezone(BEIJING)
        if local.date() == target_date:
            result.append(item)
    return result


def get_account(item):
    """从 item 中提取公众号名。"""
    author = item.get("author")
    if isinstance(author, dict):
        return author.get("name", "")
    if isinstance(author, str):
        return author
    # JSON Feed 1.1 兼容：authors 数组
    authors = item.get("authors")
    if isinstance(authors, list) and authors:
        first = authors[0]
        if isinstance(first, dict):
            return first.get("name", "")
    return ""


def normalize_item(item):
    """标准化文章字段供 render/send 使用。"""
    return {
        "account": get_account(item),
        "title": item.get("title", "(无标题)"),
        "url": item.get("url", ""),
        "image": item.get("image", ""),
        "date_published": item.get("date_modified") or item.get("date_published") or "",
        "content_html": item.get("content_html", ""),
        "id": item.get("id", ""),
    }


def fetch_daily(config, target_date=None):
    """主入口：拉取并过滤指定日期的文章（按公众号白名单可选过滤）。"""
    target_date = target_date or date.today()
    wr_cfg = config["wewe_rss"]
    whitelist = [f["name"] for f in wr_cfg.get("feeds", []) if f.get("name")]

    print(f"[fetch] 调用 {wr_cfg['base_url']}/feeds/all.json ...")
    data = fetch_all(wr_cfg["base_url"], wr_cfg.get("auth_code"))
    items = data.get("items", [])
    print(f"[fetch] 总共 {len(items)} 篇文章")

    filtered = filter_by_date(items, target_date)
    print(f"[fetch] {target_date} (北京时间) 当天文章: {len(filtered)} 篇")

    if whitelist:
        filtered = [it for it in filtered if get_account(it) in whitelist]
        print(f"[fetch] 公众号白名单过滤后: {len(filtered)} 篇 (白名单: {whitelist})")

    return [normalize_item(it) for it in filtered]


if __name__ == "__main__":
    cfg = load_config()
    arts = fetch_daily(cfg)
    print(json.dumps(arts, ensure_ascii=False, indent=2))
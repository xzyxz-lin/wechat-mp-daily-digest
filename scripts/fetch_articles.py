"""
从 WeWe RSS 拉取公众号文章。
WeWe RSS 提供标准 JSON Feed 1.1 接口：GET /feeds/all.json
"""
import json
import sys
from datetime import datetime, date
from pathlib import Path

import requests

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"


def load_config(config_path=None):
    """加载配置文件。"""
    config_file = Path(config_path) if config_path else CONFIG_PATH
    if not config_file.exists():
        print(f"ERROR: 配置文件不存在: {config_file}")
        print("请先复制 config/config.example.json 为 config/config.json 并填入真实值")
        sys.exit(1)
    with open(config_file, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_all(base_url, auth_code=None, timeout=30):
    """调用 WeWe RSS 的 /feeds/all.json 拉取所有文章。"""
    url = f"{base_url.rstrip('/')}/feeds/all.json"
    headers = {}
    if auth_code:
        # WeWe RSS 支持 Authorization 头
        headers["Authorization"] = f"Bearer {auth_code}"
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def parse_date(s):
    """解析 JSON Feed 日期字符串（ISO 8601）。"""
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        return None


def filter_by_date(items, target_date):
    """过滤指定日期（本地时区）发布的文章。"""
    result = []
    for item in items:
        pub = parse_date(item.get("date_published") or item.get("date_modified"))
        if pub and pub.date() == target_date:
            result.append(item)
    return result


def extract_account(item, feed_name_map):
    """从 item 中提取公众号名。优先顺序：authors -> author -> feed_name_map。"""
    authors = item.get("authors")
    if isinstance(authors, list) and authors:
        name = authors[0].get("name", "")
        if name:
            return name
    single = item.get("author")
    if single:
        return single
    item_id = item.get("id", "")
    feed_id = item_id.split(":")[0] if ":" in item_id else item_id
    return feed_name_map.get(feed_id, "未知公众号")


def normalize_item(item, feed_name_map):
    """标准化文章字段。"""
    item_id = item.get("id", "")
    feed_id = item_id.split(":")[0] if ":" in item_id else item_id
    account = extract_account(item, feed_name_map)
    return {
        "account": account,
        "feed_id": feed_id,
        "title": (item.get("title") or "(无标题)").strip(),
        "url": item.get("url") or item.get("external_url") or "",
        "summary": item.get("summary") or "",
        "content_html": item.get("content_html") or item.get("content_text") or "",
        "date_published": item.get("date_published") or item.get("date_modified") or "",
        "id": item_id,
    }


def fetch_daily(config, target_date=None):
    """主入口：拉取并过滤指定日期的文章。返回标准化后的文章列表。"""
    target_date = target_date or date.today()
    wr_cfg = config["wewe_rss"]
    feed_name_map = {f["feed_id"]: f["name"] for f in wr_cfg.get("feeds", [])}

    base_url = wr_cfg["base_url"]
    auth_code = wr_cfg.get("auth_code") or None

    print(f"[fetch] 调用 {base_url}/feeds/all.json ...")
    try:
        data = fetch_all(base_url, auth_code)
    except requests.exceptions.RequestException as e:
        print(f"[fetch] ERROR: 无法访问 WeWe RSS ({base_url}): {e}")
        print("[fetch] 请检查 Docker 容器是否运行 (docker ps)")
        return []

    items = data.get("items", [])
    print(f"[fetch] 总共 {len(items)} 篇文章")

    filtered = filter_by_date(items, target_date)
    print(f"[fetch] {target_date} 当天文章: {len(filtered)} 篇")

    return [normalize_item(it, feed_name_map) for it in filtered]


if __name__ == "__main__":
    cfg = load_config()
    arts = fetch_daily(cfg)
    print(json.dumps(arts, ensure_ascii=False, indent=2))
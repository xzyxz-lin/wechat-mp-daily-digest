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
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

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


def fetch_all(base_url, auth_code=None, retries=10, retry_delay=15, limit=2000):
    """调用 WeWe RSS 的 /feeds/all.json 拉取所有文章。

    带重试：开机自启动时 Docker/容器可能尚未就绪，连接失败会等待重试。
    默认最多重试 10 次、每次间隔 15 秒（约 2.5 分钟）。

    注意：wewe-rss 的 /feeds/all.json 默认只返回 30 篇（limit 默认 30），
    抓取历史日期文章时必须传足够大的 limit，否则会漏掉更早的文章。
    """
    url = f"{base_url.rstrip('/')}/feeds/all.json?limit={limit}"
    headers = {}
    if auth_code:
        headers["Authorization"] = f"Bearer {auth_code}"
    # WeWe RSS runs on this computer.  A system HTTP(S) proxy must not receive
    # localhost traffic; otherwise it can return 502 before the request reaches
    # the local Docker container.  External RSS requests keep their proxy setup.
    host = (urlparse(base_url).hostname or "").lower()
    session = requests.Session()
    if host in {"localhost", "127.0.0.1", "::1"}:
        session.trust_env = False
    last_err = None
    for i in range(retries):
        try:
            resp = session.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            last_err = e
            if i == retries - 1:
                break
            print(f"[fetch] 连接失败（第 {i+1}/{retries} 次），{retry_delay} 秒后重试: {e}")
            time.sleep(retry_delay)
    raise last_err


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


def normalize_item(item, category="公众号"):
    """标准化文章字段供 render/send 使用。

    category: 来源分类，公众号来源为「公众号」，期刊来源为「期刊」。
    """
    return {
        "account": get_account(item),
        "category": category,
        "title": item.get("title", "(无标题)"),
        "url": item.get("url", ""),
        "image": item.get("image", ""),
        "date_published": item.get("date_modified") or item.get("date_published") or "",
        "content_html": item.get("content_html", ""),
        "id": item.get("id", ""),
    }


def fetch_daily(config, target_date=None):
    """主入口：拉取并过滤指定日期的文章（按公众号白名单可选过滤）。

    返回的文章均带 category 字段（此处来源为公众号，标记为「公众号」）。
    """
    target_date = target_date or date.today()
    wr_cfg = config["wewe_rss"]
    # 白名单 -> 分类 映射（公众号来源默认「公众号」，可由 config 的 category 覆盖）
    whitelist_map = {
        f["name"]: f.get("category", "公众号")
        for f in wr_cfg.get("feeds", []) if f.get("name")
    }
    whitelist = list(whitelist_map.keys())

    print(f"[fetch] 调用 {wr_cfg['base_url']}/feeds/all.json ...")
    data = fetch_all(wr_cfg["base_url"], wr_cfg.get("auth_code"))
    items = data.get("items", [])
    print(f"[fetch] 总共 {len(items)} 篇文章")

    filtered = filter_by_date(items, target_date)
    print(f"[fetch] {target_date} (北京时间) 当天文章: {len(filtered)} 篇")

    if whitelist:
        filtered = [it for it in filtered if get_account(it) in whitelist]
        print(f"[fetch] 公众号白名单过滤后: {len(filtered)} 篇 (白名单: {whitelist})")

    result = [normalize_item(it, whitelist_map.get(get_account(it), "公众号")) for it in filtered]

    # 批量翻译标题
    translate_articles(result)

    return result


def translate_articles(articles):
    """对文章列表批量翻译标题，写入 title_zh 字段。

    翻译失败不影响主流程（title_zh 回退为原文）。
    公众号文章标题本身可能是中文，translator 会自动跳过。
    """
    if not articles:
        return
    try:
        from translator import translate_batch
        titles = [a["title"] for a in articles if a.get("title")]
        zh_map = translate_batch(titles)
        for a in articles:
            a["title_zh"] = zh_map.get(a["title"], a["title"])
        print(f"[fetch] 公众号标题翻译完成：{len(zh_map)} 条")
    except Exception as e:
        print(f"[fetch] 标题翻译失败（不影响抓取）: {e}")
        for a in articles:
            a["title_zh"] = a.get("title", "")


if __name__ == "__main__":
    cfg = load_config()
    arts = fetch_daily(cfg)
    print(json.dumps(arts, ensure_ascii=False, indent=2))

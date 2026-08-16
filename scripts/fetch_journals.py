"""
期刊论文 RSS 直连抓取模块。

与公众号走 WeWe RSS 不同，期刊没有微信账号，这里直接抓取各期刊的 RSS/Atom feed，
解析后写入与公众号相同的文章结构（多一个 category=期刊 字段），由 daily.py 统一归档。

数据源：config/journals.json（可提交、无敏感信息）。
解析：兼容 RSS (<item>) 与 Atom (<entry>) 两种格式。
容错：单个源失败（出版商拦截/超时/格式异常）仅告警并跳过，不影响其他源。

用法：
  from fetch_journals import fetch_daily
  articles = fetch_daily(config, target_date)   # 返回当天发布的期刊论文列表
"""
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).parent.parent
JOURNALS_CONFIG = PROJECT_DIR / "config" / "journals.json"
BEIJING = timezone(timedelta(hours=8))

# arXiv / Nature 等对 UA 较敏感，用一个常规浏览器 UA 提高可达性
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


# ===== LaTeX / 数学标记清理 =====
# arXiv 标题常含 $...$、\beta、_2、\textit{} 等标记，需要转为可读文本

_LATEX_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
    "Alpha": "Α", "Beta": "Β", "Gamma": "Γ", "Delta": "Δ",
    "Omega": "Ω", "Sigma": "Σ", "Pi": "Π", "Lambda": "Λ",
}

def clean_latex(text):
    """清理标题中的 LaTeX 数学标记，返回可读纯文本。"""
    import re
    if not text:
        return text
    t = text

    # 1. 先处理 $...$（可能嵌套，从内到外）
    for _ in range(3):
        t = re.sub(r"\$([^$]+)\$", lambda m: clean_latex(m.group(1)), t)

    # 2. \textit{...} \textbf{...} \textrm{...} \emph{...} → 只保留内容
    t = re.sub(r"\\(?:textit|textbf|textrm|emph)\{([^}]*)\}", r"\1", t)

    # 3. 希腊字母 \beta \alpha 等 → Unicode
    for cmd, uni in _LATEX_GREEK.items():
        t = t.replace(f"\\{cmd}", uni)
        # 也处理 {\beta} 形式
        t = t.replace(f"{{{uni}}}", uni)

    # 4. 下标 _{xx} 或 _x → 下标括号表示 (如 Ga₂O₃)
    def sub_repl(m):
        content = m.group(1) or m.group(2) or ""
        return "₍" + content + "₎"
    t = re.sub(r"_(?:\{([^}]*)\}|(\w))", sub_repl, t)

    # 5. 上标 ^{xx} 或 ^x
    def sup_repl(m):
        content = m.group(1) or m.group(2) or ""
        return "⁽" + content + "⁾"
    t = re.sub(r"\^(?:\{([^}]*)\}|(\w))", sup_repl, t)

    # 6. 清理剩余的孤立的 { } （LaTeX 分组符）
    t = re.sub(r"\{([^{}]*)\}", r"\1", t)

    # 7. 清理常见 LaTeX 命令残留
    t = re.sub(r"\\(rm|sf|it|bf|cal|mathrm|mathbb|mathbf|mathit|sim|ldots|cdots|times|div|pm|mp|leq|geq|neq|approx|equiv|infty|partial|nabla|forall|exists|rightarrow|leftarrow|Rightarrow|Leftarrow|leftrightarrow|to|Rightarrow|Leftarrow|mid|quad|qquad|hspace|vspace|noindent)", "", t)

    # 8. 收尾：去掉多余空白
    t = re.sub(r"\s+", " ", t).strip()

    return t


def load_journals(path=None):
    cfg_path = Path(path) if path else JOURNALS_CONFIG
    if not cfg_path.exists():
        print(f"[journals] 配置文件不存在: {cfg_path}，跳过期刊抓取")
        return []
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("journals", [])
    except Exception as e:
        print(f"[journals] 读取配置失败: {e}")
        return []


def _parse_date(s):
    """解析多种 RSS/Atom 日期格式，返回带时区的 datetime（无法解析返回 None）。"""
    if not s:
        return None
    s = s.strip()
    # 常见格式：RFC 822 (RSS) / ISO 8601 (Atom)
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%Y-%m-%d",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # 最后尝试 fromisoformat（容错 Z）
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _date_from_description(text):
    """提取 ScienceDirect RSS 写在 description 内的 Publication date。"""
    import html
    import re

    plain = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    match = re.search(
        r"publication\s+date\s*:\s*(.+?)(?=\s*(?:source|author\(s\))\s*:|$)",
        plain,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _text(el):
    """取 XML 元素的 text（含 CDATA）。"""
    if el is None:
        return ""
    return (el.text or "").strip()


def _find_text(item, tag_names):
    """在 item 下按多个候选标签名（含命名空间）查找文本。

    命名空间匹配用 Clark notation 的 local name：tag == "{ns}name" 时用
    tag.endswith("}name") 判断（注意 RSS 1.0 命名空间 URI 以 / 结尾，
    不能写成 endswith("/name")）。
    """
    for tag in tag_names:
        el = item.find(tag)
        if el is not None and (el.text or "").strip():
            return (el.text or "").strip()
        for match in item.iter():
            if match.tag == tag or match.tag.endswith("}" + tag):
                if (match.text or "").strip():
                    return (match.text or "").strip()
    return ""


def _find_link(item):
    """提取文章链接：RSS 用 <link> 文本；Atom 用 <link href=>。"""
    # RSS: <link>text</link>
    link = item.find("link")
    if link is not None:
        txt = (link.text or "").strip()
        if txt:
            return txt
        # Atom: <link href="..."/>
        href = link.get("href")
        if href:
            return href
    # Atom 命名空间 <link href>
    for el in item.iter():
        if el.tag.endswith("}link") or el.tag == "link":
            href = el.get("href")
            if href:
                return href
    return ""


def _local_date(pub):
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=BEIJING)
    return pub.astimezone(BEIJING).date()


def parse_feed(xml_text, journal_name):
    """解析单个 feed 的 XML，返回文章 dict 列表（不含日期过滤）。

    兼容 RSS 2.0（<item>）、RSS 1.0/RDF（命名空间 <item>）、Atom（<entry>）。
    采用命名空间无关的匹配，避免漏解析带命名空间的元素。
    """
    import xml.etree.ElementTree as ET

    articles = []
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print(f"[journals] 解析 {journal_name} XML 失败: {e}")
        return articles

    # 命名空间无关：收集所有 item / entry（兼容各种命名空间）
    items = [
        el for el in root.iter()
        if el.tag == "item" or el.tag.endswith("}item")
        or el.tag == "entry" or el.tag.endswith("}entry")
    ]
    if not items:
        items = root.findall(".//item")
        if not items:
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    for it in items:
        title = _find_text(it, ["title"])
        title = clean_latex(title)  # 清理 arXiv 等源标题中的 LaTeX 标记
        link = _find_link(it)
        summary = _find_text(it, ["description", "summary", "content", "content:encoded", "encoded"])
        pub_raw = _find_text(it, ["pubDate", "published", "updated", "date", "dc:date"])
        if not pub_raw:
            pub_raw = _date_from_description(summary)
        guid = _find_text(it, ["guid", "id", "link"]) or link
        if not title:
            continue
        pub = _parse_date(pub_raw)
        articles.append({
            "account": journal_name,
            "category": "期刊",
            "title": title,
            "url": link,
            "image": "",
            "date_published": pub.isoformat() if pub else (pub_raw or ""),
            "content_html": "",
            "summary": (summary or title)[:300],
            "id": guid or link or title,
            "_pub_date": pub,  # 内部用，归档前移除
        })
    return articles


def _crossref_date(work):
    """从 Crossref work 中提取最可靠的发布日期。"""
    for field in ("published-online", "published-print", "published", "issued", "created"):
        parts = (work.get(field) or {}).get("date-parts") or []
        if not parts or not parts[0]:
            continue
        try:
            values = parts[0]
            return datetime(
                int(values[0]),
                int(values[1]) if len(values) > 1 else 1,
                int(values[2]) if len(values) > 2 else 1,
                tzinfo=BEIJING,
            )
        except (ValueError, TypeError, IndexError):
            continue
    return None


def fetch_crossref_one(journal, target_date, proxy=None, timeout=25,
                       seen_urls=None, lookback_days=7):
    """用 Crossref 公开元数据补齐已取消或拦截 RSS 的出版商期刊。"""
    from datetime import timedelta

    name = journal.get("name", "未知期刊")
    issn = (journal.get("issn") or "").strip()
    if not issn:
        print(f"[journals] {name} 未配置 Crossref ISSN，跳过")
        return []

    cutoff = target_date - timedelta(days=lookback_days)
    params = {
        "filter": f"from-pub-date:{cutoff.isoformat()},until-pub-date:{target_date.isoformat()}",
        "sort": "published",
        "order": "desc",
        "rows": 100,
        "select": "DOI,title,URL,published-online,published-print,published,issued,abstract",
    }
    try:
        resp = requests.get(
            f"https://api.crossref.org/journals/{issn}/works",
            params=params,
            headers={**_HEADERS, "User-Agent": "Paper Observatory Crossref metadata fetcher (mailto:local@example.invalid)"},
            timeout=timeout,
            proxies={"http": proxy, "https": proxy} if proxy else None,
        )
        if resp.status_code != 200:
            print(f"[journals] {name} Crossref HTTP {resp.status_code}，跳过")
            return []
        works = (resp.json().get("message") or {}).get("items") or []
    except Exception as e:
        print(f"[journals] {name} Crossref 抓取失败: {e}")
        return []

    kept = []
    for work in works:
        title_parts = work.get("title") or []
        title = clean_latex(title_parts[0] if title_parts else "")
        pub = _crossref_date(work)
        doi = (work.get("DOI") or "").strip()
        url = (work.get("URL") or (f"https://doi.org/{doi}" if doi else "")).strip()
        if not title or not pub:
            continue
        local_d = _local_date(pub)
        if local_d < cutoff or local_d > target_date:
            continue
        if seen_urls and url and url in seen_urls:
            continue
        abstract = (work.get("abstract") or "").strip()
        kept.append({
            "account": name,
            "category": "期刊",
            "title": title,
            "url": url,
            "image": "",
            "date_published": pub.isoformat(),
            "content_html": "",
            "summary": (abstract or title)[:300],
            "id": doi or url or title,
        })
    print(f"[journals] {name}: Crossref 共 {len(works)} 篇，窗口内新增 {len(kept)} 篇")
    return kept


def fetch_one(journal, target_date, proxy=None, timeout=25, seen_urls=None, lookback_days=7):
    """抓取单个期刊 feed，返回未在 seen_urls 中的近期文章列表。

    Args:
        seen_urls: 已存档文章的 URL 集合（用于去重），None 表示不去重
        lookback_days: 只抓取发布日期在过去 N 天内的文章（默认 7 天，
                       覆盖周更期刊的发布节奏 + 旧 RSS 项）

    修复历史：
        原版用严格日期匹配（_local_date == target_date），导致周更期刊
        （Nature Communications 等）昨日发布的文章被全部漏掉。
        改为「近期窗口 + URL 去重」：只要 RSS 里有的近期文章、且本地没有，
        都视为新增。
    """
    from datetime import timedelta

    name = journal.get("name", "未知期刊")
    if journal.get("source_type", "rss").lower() == "crossref":
        return fetch_crossref_one(journal, target_date, proxy=proxy, timeout=timeout,
                                  seen_urls=seen_urls, lookback_days=lookback_days)
    url = journal.get("rss", "")
    if not url:
        print(f"[journals] {name} 无 RSS 地址，跳过")
        return []
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout,
                            proxies={"http": proxy, "https": proxy} if proxy else None)
        if resp.status_code != 200:
            print(f"[journals] {name} HTTP {resp.status_code}（可能被出版商拦截），跳过")
            return []
        arts = parse_feed(resp.text, name)

        # 近期窗口 + 去重过滤
        cutoff = target_date - timedelta(days=lookback_days)
        kept = []
        skipped_old = 0
        skipped_dup = 0
        skipped_no_date = 0
        for a in arts:
            pub = a.get("_pub_date")
            if not pub:
                skipped_no_date += 1
                continue
            local_d = _local_date(pub)
            if local_d < cutoff:
                skipped_old += 1
                continue
            url_key = a.get("url") or a.get("id") or ""
            if seen_urls and url_key and url_key in seen_urls:
                skipped_dup += 1
                continue
            # 保留这篇
            a.pop("_pub_date", None)
            kept.append(a)

        print(f"[journals] {name}: feed 共 {len(arts)} 篇 "
              f"(窗口内新增 {len(kept)} | 过旧 {skipped_old} | 已存档 {skipped_dup} | 无日期 {skipped_no_date})")
        return kept
    except Exception as e:
        print(f"[journals] {name} 抓取失败: {e}")
        return []


def _load_seen_urls(target_date):
    """从本地存档目录加载已见文章 URL 集合（用于期刊去重）。

    扫描 [target_date - 30 天, target_date] 范围内所有 articles.json，
    收集所有 url / id / link 字段作为 seen set。
    """
    from datetime import timedelta

    # 从 config.json 读取本地存档目录（与 daily.py 一致）
    cfg_path = PROJECT_DIR / "config" / "config.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    else:
        cfg = {}
    archive_dir = Path(cfg.get("output", {}).get("local_dir", str(PROJECT_DIR / "每日论文推送")))
    if not archive_dir.is_dir():
        return set()

    seen: set[str] = set()
    cutoff = target_date - timedelta(days=30)
    for day_dir in sorted(archive_dir.iterdir(), reverse=True):
        if not day_dir.is_dir():
            continue
        jp = day_dir / "articles.json"
        if not jp.exists():
            continue
        # 解析目录名 YYYY.M.D → date 对象
        try:
            parts = day_dir.name.split(".")
            if len(parts) == 3:
                d = date(int(parts[0]), int(parts[1]), int(parts[2]))
                if d < cutoff:
                    break  # 太旧了，没必要再扫
        except Exception:
            continue
        try:
            arts = json.load(open(jp, "r", encoding="utf-8"))
            for a in arts:
                for key in ("url", "id", "link"):
                    v = a.get(key)
                    if v:
                        seen.add(v)
        except Exception:
            continue
    return seen


def fetch_daily(config, target_date=None, lookback_days=7):
    """主入口：抓取所有期刊，返回 target_date 前后 N 天内未存档的新文章列表。

    每篇文章附带 title_zh（中文翻译标题），翻译失败时保留原文。

    修复：原版只取 pubDate == target_date 的文章，导致周更期刊漏掉。
    现在改为「近期窗口 + URL 去重」，能稳定抓到 Nature Communications 等
    期刊最新一周内发布的所有文章。
    """
    target_date = target_date or date.today()
    journals = load_journals()
    if not journals:
        return []
    proxy = (config.get("journals_proxy") or "").strip() or None

    # 加载已存档 URL（避免重复入库）
    seen = _load_seen_urls(target_date)
    print(f"[journals] 本地存档共 {len(seen)} 个 URL（去重基准）")

    window_start = target_date - timedelta(days=lookback_days)
    print(f"\n[journals] 抓取期刊（窗口：{window_start} ~ {target_date}，北京时间），共 {len(journals)} 个源")
    result = []
    for j in journals:
        print(f"[journals] 正在抓取：{j.get('name', '未知期刊')}")
        result.extend(fetch_one(j, target_date, proxy=proxy,
                                seen_urls=seen, lookback_days=lookback_days))
        time.sleep(0.3)  # 礼貌性限速，避免被封

    # 批量翻译标题
    if result:
        try:
            from translator import translate_batch
            titles = [a["title"] for a in result if a.get("title")]
            zh_map = translate_batch(titles)
            for a in result:
                a["title_zh"] = zh_map.get(a["title"], a["title"])
            print(f"[journals] 翻译完成：{len(zh_map)} 条标题")
        except Exception as e:
            print(f"[journals] 翻译失败（不影响抓取）: {e}")
            for a in result:
                a["title_zh"] = a.get("title", "")

    print(f"[journals] 本次新增期刊论文合计 {len(result)} 篇")
    return result


if __name__ == "__main__":
    cfg = {"journals_proxy": ""}
    arts = fetch_daily(cfg)
    print(json.dumps(arts, ensure_ascii=False, indent=2))

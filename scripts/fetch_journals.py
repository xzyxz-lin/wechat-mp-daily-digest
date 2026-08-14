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
        pub_raw = _find_text(it, ["pubDate", "published", "updated", "date", "dc:date"])
        summary = _find_text(it, ["description", "summary", "content", "content:encoded", "encoded"])
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


def fetch_one(journal, target_date, proxy=None, timeout=25):
    """抓取单个期刊 feed，返回 target_date(北京) 当天发布的文章列表。"""
    name = journal.get("name", "未知期刊")
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
        today = [a for a in arts if a.get("_pub_date") and _local_date(a["_pub_date"]) == target_date]
        # 清理内部字段
        for a in today:
            a.pop("_pub_date", None)
        print(f"[journals] {name}: feed 共 {len(arts)} 篇，{target_date} 当天 {len(today)} 篇")
        return today
    except Exception as e:
        print(f"[journals] {name} 抓取失败: {e}")
        return []


def fetch_daily(config, target_date=None):
    """主入口：抓取所有期刊，返回 target_date(北京) 当天发布的文章列表。

    每篇文章附带 title_zh（中文翻译标题），翻译失败时保留原文。
    """
    target_date = target_date or date.today()
    journals = load_journals()
    if not journals:
        return []
    proxy = (config.get("journals_proxy") or "").strip() or None

    print(f"\n[journals] 抓取期刊（{target_date} 北京时间），共 {len(journals)} 个源")
    result = []
    for j in journals:
        result.extend(fetch_one(j, target_date, proxy=proxy))
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

    print(f"[journals] 当天期刊论文合计 {len(result)} 篇")
    return result


if __name__ == "__main__":
    cfg = {"journals_proxy": ""}
    arts = fetch_daily(cfg)
    print(json.dumps(arts, ensure_ascii=False, indent=2))

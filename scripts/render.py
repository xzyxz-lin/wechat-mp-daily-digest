"""
将文章列表渲染为 HTML 和 Markdown。
- HTML：紧凑目录模式（分类→来源→文章链接+中文副标题）
- Markdown：清爽简洁的目录式列表
"""
import re

from bs4 import BeautifulSoup
from jinja2 import Template


# ===== LaTeX 标记清理（与 fetch_journals.py 保持一致）=====
_LATEX_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
    "Alpha": "Α", "Beta": "Β", "Gamma": "Γ", "Delta": "Δ",
    "Omega": "Ω", "Sigma": "Σ", "Pi": "Π", "Lambda": "Λ",
}

def _clean_latex(text):
    """清理标题中的 LaTeX 数学标记（render 阶段安全网）。"""
    if not text:
        return text
    t = text
    for _ in range(3):
        t = re.sub(r"\$([^$]+)\$", lambda m: _clean_latex(m.group(1)), t)
    t = re.sub(r"\\(?:textit|textbf|textrm|emph)\{([^}]*)\}", r"\1", t)
    for cmd, uni in _LATEX_GREEK.items():
        t = t.replace(f"\\{cmd}", uni)
        t = t.replace(f"{{{uni}}}", uni)
    t = re.sub(r"_(?:\{([^}]*)\}|(\w))", lambda m: "₍" + (m.group(1) or m.group(2)) + "₎", t)
    t = re.sub(r"\^(?:\{([^}]*)\}|(\w))", lambda m: "⁽" + (m.group(1) or m.group(2)) + "⁾", t)
    t = re.sub(r"\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\(rm|sf|it|bf|cal|mathrm|mathbb|mathbf|mathit|sim|ldots|cdots|times|div|pm|mp|leq|geq|neq|approx|equiv|infty|partial|nabla|forall|exists|rightarrow|leftarrow|Rightarrow|Leftarrow|leftrightarrow|to|mid|quad|qquad)", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{{ title }}</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 860px; margin: 24px auto; padding: 0 20px; line-height: 1.65; background: #fafafa; color: #222; }
h1 { font-size: 23px; border-bottom: 2px solid #1855a5; padding-bottom: 8px; margin-bottom: 16px; }
.toc { background: #fff; padding: 18px 24px; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); margin: 16px 0; }
.toc h2 { margin: 0 0 10px; font-size: 15px; color: #888; letter-spacing: 1px; text-transform: uppercase; }
.toc ul { padding-left: 0; list-style: none; }
.toc li { margin: 0; }
.toc > ul > li { margin-bottom: 12px; }
.toc > ul > li > b { font-size: 17px; color: #1855a5; }
.toc > ul > li > ul { padding-left: 20px; margin-top: 6px; }
.toc > ul > li > ul > li { margin-bottom: 6px; }
.toc > ul > li > ul > li > b { font-size: 14.5px; color: #333; }
.toc > ul > li > ul > li > ul { padding-left: 18px; margin-top: 4px; }
.toc > ul > li > ul > li > ul > li { margin-bottom: 3px; font-size: 14px; }
.toc a { color: #1855a5; text-decoration: none; }
.toc a:hover { text-decoration: underline; }
.zh { color: #777; font-size: 12.5px; margin-left: 4px; }
.cat-badge { display: inline-block; font-size: 10px; padding: 1px 7px; border-radius: 8px; color: white; margin-left: 5px; vertical-align: 1px; }
.cat-badge.mp { background: #e07020; }
.cat-badge.journal { background: #1a7a59; }
.cat-badge.fund { background: #7a5aa0; }
.empty { color: #999; text-align: center; padding: 40px; font-size: 15px; }
.footer { text-align: center; color: #bbb; font-size: 11.5px; margin-top: 30px; padding-top: 16px; border-top: 1px solid #eee; }
</style>
</head>
<body>
<h1>{{ title }}</h1>
{% if groups %}
<div class="toc">
<h2>📋 目录</h2>
<ul>
{% for grp in groups %}
<li><b>{{ grp.category_label }}</b><span class="cat-badge {{ grp.cls }}">{{ grp.total }} 篇</span>
<ul>
{% for sub in grp.sub_groups %}
<li><b>{{ sub.account }}</b>{% if sub.cat_tag %} <span class="cat-badge {{ sub.cls }}">{{ sub.articles|length }} 篇</span>{% endif %}
<ul>
{% for a in sub.articles %}
<li><a href="{{ a.url }}" target="_blank">{{ a.title }}</a>{% if a.title_zh %} <span class="zh">{{ a.title_zh }}</span>{% endif %}</li>
{% endfor %}
</ul>
</li>
{% endfor %}
</ul>
</li>
{% endfor %}
</ul>
</div>
{% else %}
<div class="empty">今天暂无新文章推送</div>
{% endif %}
<div class="footer">由 WorkBuddy 自动生成 · 论文观察台</div>
</body>
</html>"""


def html_summary(content_html, max_chars=200, fallback=""):
    """从 content_html 提取纯文本摘要。

    若 content_html 为空（wewe-rss 默认非全文模式），返回 fallback（如文章标题）。
    """
    if not content_html:
        return fallback
    try:
        soup = BeautifulSoup(content_html, "lxml")
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "..."
        return text
    except Exception:
        return fallback


def make_anchor(idx):
    return f"art-{idx}"


def group_articles(articles, group_by_account=True, sort_desc=True):
    """按分类（公众号/期刊）→ 来源 两层分组文章。

    返回结构：
    [
      {
        "category": "公众号",
        "category_label": "📱 公众号",
        "total": 5,
        "accounts": ["环境人Environmentor", ...],
        "all_articles": [...],
        "sub_groups": [
          {"account": "环境人Environmentor", "cat_tag": "公众号", "cls": "mp", "articles": [...]},
        ]
      },
      ...
    ]
    """
    if not articles:
        return []

    # 分类映射
    CAT_LABELS = {
        "公众号": "📱 公众号",
        "期刊": "📰 期刊论文",
        "基金": "💰 基金",
    }
    CAT_TAG = {
        "公众号": ("公众号", "mp"),
        "期刊": ("期刊", "journal"),
        "基金": ("基金", "fund"),
    }

    # 先按分类分组
    cat_dict: dict[str, list] = {}
    for a in articles:
        cat = a.get("category") or "公众号"
        cat_dict.setdefault(cat, []).append(a)

    result = []
    for cat in ["公众号", "期刊", "基金"]:
        items = cat_dict.get(cat, [])
        if not items:
            continue

        # 按子来源（account）再分组
        sub_dict: dict[str, list] = {}
        for a in items:
            key = a.get("account") or "未知源"
            sub_dict.setdefault(key, []).append(a)

        sub_groups = []
        all_accounts = []
        all_arts = []
        for acc, arts in sorted(sub_dict.items()):
            arts_sorted = sorted(arts, key=lambda x: x.get("date_published") or "", reverse=sort_desc)
            tag, cls = CAT_TAG.get(cat, (cat, ""))
            sub_groups.append({
                "account": acc,
                "cat_tag": tag,
                "cls": cls,
                "articles": arts_sorted,
            })
            all_accounts.append(acc)
            all_arts.extend(arts_sorted)

        # 全部文章按时间排序（用于目录）
        all_arts_sorted = sorted(all_arts, key=lambda x: x.get("date_published") or "", reverse=sort_desc)
        for i, a in enumerate(all_arts_sorted):
            a["anchor"] = make_anchor(i)

        result.append({
            "category": cat,
            "category_label": CAT_LABELS.get(cat, cat),
            "cls": CAT_TAG.get(cat, ("", ""))[1],
            "total": len(items),
            "accounts": all_accounts,
            "all_articles": all_arts_sorted,
            "sub_groups": sub_groups,
        })

    return result


def render_html(articles, target_date_str, group_by_account=True, sort_desc=True, include_toc=True):
    """渲染 HTML 字符串（紧凑目录模式）。"""
    # 渲染前清理所有标题和翻译的 LaTeX 标记
    for a in articles:
        a["title"] = _clean_latex(a.get("title", ""))
        if a.get("title_zh"):
            a["title_zh"] = _clean_latex(a["title_zh"])
    groups = group_articles(articles, group_by_account, sort_desc)
    tpl = Template(HTML_TEMPLATE)
    return tpl.render(
        title=f"论文推送 - {target_date_str}",
        groups=groups,
        toc=include_toc,
    )


def render_markdown(articles, target_date_str, group_by_account=True, sort_desc=True):
    """渲染 Markdown 字符串（紧凑目录模式：分类→来源→文章链接+中文副标题）。"""
    # 渲染前清理所有标题和翻译的 LaTeX 标记
    for a in articles:
        a["title"] = _clean_latex(a.get("title", ""))
        if a.get("title_zh"):
            a["title_zh"] = _clean_latex(a["title_zh"])
    lines = []
    mp_count = sum(1 for a in articles if a.get("category") == "公众号")
    j_count = sum(1 for a in articles if a.get("category") == "期刊")
    f_count = sum(1 for a in articles if a.get("category") == "基金")
    total = len(articles)

    lines.append(f"# 论文推送 - {target_date_str}\n\n")
    parts = []
    if mp_count:
        parts.append(f"📱 公众号 **{mp_count}** 篇")
    if j_count:
        parts.append(f"📰 期刊 **{j_count}** 篇")
    if f_count:
        parts.append(f"💰 基金 **{f_count}** 篇")
    lines.append(f"共 **{total}** 篇（{' · '.join(parts)}）。\n\n---\n\n")

    groups = group_articles(articles, group_by_account, sort_desc)
    if not groups:
        lines.append("_今天暂无新文章推送_\n")
        return "".join(lines)

    for grp in groups:
        lines.append(f"## {grp['category_label']}（{grp['total']} 篇）\n\n")
        for sub in grp["sub_groups"]:
            acc = sub["account"]
            n = len(sub["articles"])
            lines.append(f"### {acc}（{n} 篇）\n\n")
            for a in sub["articles"]:
                lines.append(f"- [{a['title']}]({a['url']})")
                if a.get("title_zh"):
                    lines.append(f"  *{a['title_zh']}*")
                else:
                    lines.append("")
                lines.append("")
        lines.append("---\n\n")

    lines.append("_由 WorkBuddy 自动生成 · 论文观察台_\n")
    return "".join(lines)
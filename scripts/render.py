"""
将文章列表渲染为 HTML 和 Markdown。
- HTML：带样式、按公众号分组、含目录
- Markdown：清爽简洁、按公众号分组、含链接
"""
import re

from bs4 import BeautifulSoup
from jinja2 import Template

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{{ title }}</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 920px; margin: 24px auto; padding: 0 20px; line-height: 1.7; background: #fafafa; color: #222; }
h1 { font-size: 24px; border-bottom: 2px solid #1855a5; padding-bottom: 8px; }
.toc { background: #f0f4f8; padding: 16px 24px; border-radius: 8px; margin: 16px 0; }
.toc h2 { margin-top: 0; font-size: 16px; }
.toc ul { padding-left: 20px; }
.account-group { margin: 32px 0; }
.account-name { font-size: 20px; color: #1855a5; border-left: 4px solid #1855a5; padding-left: 12px; margin-bottom: 16px; }
.article { background: white; padding: 16px 20px; margin: 12px 0; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.article h3 { margin: 0 0 8px; font-size: 17px; }
.article h3 a { color: #1855a5; text-decoration: none; }
.article .meta { color: #888; font-size: 12px; margin-bottom: 8px; }
.article .summary { color: #444; font-size: 14px; }
.empty { color: #888; text-align: center; padding: 32px; }
.footer { text-align: center; color: #aaa; font-size: 12px; margin-top: 40px; padding: 16px; }
</style>
</head>
<body>
<h1>{{ title }}</h1>
{% if toc and groups %}
<div class="toc">
<h2>目录</h2>
<ul>
{% for grp in groups %}
<li><b>{{ grp.account }}</b>（{{ grp.articles|length }} 篇）
<ul>
{% for a in grp.articles %}
<li><a href="#{{ a.anchor }}">{{ a.title }}</a></li>
{% endfor %}
</ul>
</li>
{% endfor %}
</ul>
</div>
{% endif %}
{% for grp in groups %}
<div class="account-group">
<div class="account-name">{{ grp.account }}</div>
{% for a in grp.articles %}
<div class="article" id="{{ a.anchor }}">
<h3><a href="{{ a.url }}" target="_blank">{{ a.title }}</a></h3>
<div class="meta">{{ a.date_published }}{% if a.account %} · {{ a.account }}{% endif %}</div>
{% if a.summary %}<div class="summary">{{ a.summary }}</div>{% endif %}
<p><a href="{{ a.url }}" target="_blank">👉 阅读原文</a></p>
</div>
{% endfor %}
</div>
{% endfor %}
{% if not groups %}
<div class="empty">今天暂无新文章推送</div>
{% endif %}
<div class="footer">由 WorkBuddy 自动生成 · 公众号每日推送</div>
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
    """按公众号分组文章。"""
    if not articles:
        return []
    if not group_by_account:
        items = sorted(articles, key=lambda x: x.get("date_published") or "", reverse=sort_desc)
        return [{"account": "今日全部", "articles": items}]

    groups_dict = {}
    for a in articles:
        key = a.get("account") or "未知公众号"
        groups_dict.setdefault(key, []).append(a)

    groups = []
    for account, items in groups_dict.items():
        items_sorted = sorted(items, key=lambda x: x.get("date_published") or "", reverse=sort_desc)
        groups.append({"account": account, "articles": items_sorted})
    groups.sort(key=lambda g: g["account"])
    return groups


def render_html(articles, target_date_str, group_by_account=True, sort_desc=True, include_toc=True):
    """渲染 HTML 字符串。"""
    for i, a in enumerate(articles):
        # 摘要：content_html 为空时用 title 兜底
        a["summary"] = html_summary(a.get("content_html", ""), 200, fallback=a.get("title", ""))
        a["anchor"] = make_anchor(i)

    groups = group_articles(articles, group_by_account, sort_desc)
    tpl = Template(HTML_TEMPLATE)
    return tpl.render(
        title=f"每日论文推送 - {target_date_str}",
        groups=groups,
        toc=include_toc,
    )


def render_markdown(articles, target_date_str, group_by_account=True, sort_desc=True):
    """渲染 Markdown 字符串。"""
    lines = []
    lines.append(f"# 每日论文推送 - {target_date_str}\n\n")
    lines.append(f"共 **{len(articles)}** 篇文章。\n\n---\n\n")

    groups = group_articles(articles, group_by_account, sort_desc)
    if not groups:
        lines.append("_今天暂无新文章推送_\n")
        return "".join(lines)

    for grp in groups:
        lines.append(f"## {grp['account']}\n\n")
        for a in grp["articles"]:
            lines.append(f"### [{a['title']}]({a['url']})\n\n")
            if a.get("date_published"):
                lines.append(f"*{a['date_published']}*\n\n")
            summary = html_summary(a.get("content_html", ""), 200, fallback=a.get("title", ""))
            if summary:
                lines.append(f"> {summary}\n\n")
            lines.append(f"[👉 阅读原文]({a['url']})\n\n---\n\n")

    lines.append("\n_由 WorkBuddy 自动生成_\n")
    return "".join(lines)
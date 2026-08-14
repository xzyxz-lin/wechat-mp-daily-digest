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
.category-group { margin: 32px 0; }
.category-header { font-size: 22px; color: #1855a5; border-left: 4px solid #1855a5; padding-left: 12px; margin-bottom: 4px; }
.category-desc { color: #888; font-size: 13px; margin-left: 16px; margin-bottom: 16px; }
.account-group { margin: 20px 0; }
.account-name { font-size: 17px; color: #333; border-left: 3px solid #ccc; padding-left: 10px; margin-bottom: 12px; }
.article { background: white; padding: 16px 20px; margin: 12px 0; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.article h3 { margin: 0 0 4px; font-size: 17px; }
.article h3 a { color: #1855a5; text-decoration: none; }
.article .subtitle { color: #444; font-size: 15px; margin: 6px 0 10px; padding: 8px 12px; background: #f8f9fa; border-left: 3px solid #90c4a0; border-radius: 0 6px 6px 0; line-height: 1.6; }
.article .subtitle::before { content: "— "; color: #90c4a0; font-weight: bold; margin-right: 4px; }
.article .meta { color: #888; font-size: 12px; margin-bottom: 8px; }
.cat-tag { display: inline-block; font-size: 11px; padding: 1px 8px; border-radius: 10px; color: white; }
.cat-tag.mp { background: #e07020; }
.cat-tag.journal { background: #1a7a59; }
.cat-tag.fund { background: #7a5aa0; }
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
<li><b>{{ grp.category_label }}</b>（{{ grp.total }} 篇）
<ul>
{% for sub in grp.sub_groups %}
<li>{{ sub.account }}（{{ sub.articles|length }} 篇）
<ul>
{% for a in sub.articles %}
<li><a href="#{{ a.anchor }}">{{ a.title }}</a>{% if a.title_zh %} <span style="color:#888;font-size:12px">{{ a.title_zh }}</span>{% endif %}</li>
{% endfor %}
</ul>
</li>
{% endfor %}
</ul>
</li>
{% endfor %}
</ul>
</div>
{% endif %}
{% for grp in groups %}
<div class="category-group">
<div class="category-header">{{ grp.category_label }}</div>
<div class="category-desc">共 {{ grp.sub_groups|length }} 个来源 · {{ grp.total }} 篇</div>
{% for sub in grp.sub_groups %}
<div class="account-group">
<div class="account-name">{{ sub.account }}{% if sub.cat_tag %} <span class="cat-tag {{ sub.cls }}">{{ sub.cat_tag }}</span>{% endif %}</div>
{% for a in sub.articles %}
<div class="article" id="{{ a.anchor }}">
<h3><a href="{{ a.url }}" target="_blank">{{ a.title }}</a></h3>
{% if a.title_zh %}<div class="subtitle">{{ a.title_zh }}</div>{% endif %}
<div class="meta">📅 {{ a.date_published }}{% if a.account %} · 来源：{{ a.account }}{% endif %}{% if a.cat_tag %} · <span class="cat-tag {{ a.cls }}">{{ a.cat_tag }}</span>{% endif %}</div>
{% if a.summary %}<div class="summary">{{ a.summary }}</div>{% endif %}
<p><a href="{{ a.url }}" target="_blank">👉 阅读原文</a></p>
</div>
{% endfor %}
</div>
{% endfor %}
</div>
{% endfor %}
{% if not groups %}
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
            "total": len(items),
            "accounts": all_accounts,
            "all_articles": all_arts_sorted,
            "sub_groups": sub_groups,
        })

    return result


def render_html(articles, target_date_str, group_by_account=True, sort_desc=True, include_toc=True):
    """渲染 HTML 字符串。"""
    groups = group_articles(articles, group_by_account, sort_desc)
    tpl = Template(HTML_TEMPLATE)
    return tpl.render(
        title=f"论文推送 - {target_date_str}",
        groups=groups,
        toc=include_toc,
    )


def render_markdown(articles, target_date_str, group_by_account=True, sort_desc=True):
    """渲染 Markdown 字符串（含中文副标题和分类标注）。"""
    lines = []
    mp_count = sum(1 for a in articles if a.get("category") == "公众号")
    j_count = sum(1 for a in articles if a.get("category") == "期刊")
    f_count = sum(1 for a in articles if a.get("category") == "基金")
    total = len(articles)

    lines.append(f"# 论文推送 - {target_date_str}\n\n")
    parts = []
    if mp_count:
        parts.append(f"公众号 **{mp_count}** 篇")
    if j_count:
        parts.append(f"期刊 **{j_count}** 篇")
    if f_count:
        parts.append(f"基金 **{f_count}** 篇")
    lines.append(f"共 **{total}** 篇（{' + '.join(parts)}）。\n\n---\n\n")

    groups = group_articles(articles, group_by_account, sort_desc)
    if not groups:
        lines.append("_今天暂无新文章推送_\n")
        return "".join(lines)

    for grp in groups:
        lines.append(f"## {grp['category_label']}\n\n")
        for sub in grp["sub_groups"]:
            acc = sub["account"]
            tag = sub["cat_tag"]
            lines.append(f"### {acc} `{tag}`\n\n")
            for a in sub["articles"]:
                lines.append(f"- **[{a['title']}]({a['url']})**\n")
                if a.get("title_zh"):
                    lines.append(f"  > — *{a['title_zh']}*\n")
                if a.get("date_published"):
                    lines.append(f"  📅 {a['date_published']}\n")
                summary = html_summary(a.get("content_html", ""), 200, fallback=a.get("title", ""))
                if summary and summary != a.get("title", ""):
                    lines.append(f"  > {summary}\n")
                lines.append("\n")

    lines.append("---\n\n_由 WorkBuddy 自动生成 · 论文观察台_\n")
    return "".join(lines)
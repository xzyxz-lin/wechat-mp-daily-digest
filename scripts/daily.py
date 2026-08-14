"""
主入口：抓取 -> 渲染 -> 保存本地 -> 发送邮件。
命令行参数：
  --start 2026-08-12   起始日期（默认今天）
  --end   2026-08-14   结束日期（默认等于 start）
  --date  2026-08-13   单天抓取（等价于 --start=--end=该日期）
  --dry-run            只抓取不写本地不发邮件
  --no-email           跳过邮件
  --no-local           跳过本地存档
  --force              强制重跑（即使当天已推送）
  --config <path>      指定配置文件
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from fetch_articles import load_config, fetch_daily
from fetch_journals import fetch_daily as fetch_journals_daily
from render import render_html, render_markdown
from send_email import send_email


def parse_args():
    p = argparse.ArgumentParser(description="每日论文推送（公众号 + 期刊）")
    p.add_argument("--start", help="起始日期 (YYYY-MM-DD)，默认今天")
    p.add_argument("--end", help="结束日期 (YYYY-MM-DD)，默认等于 start")
    p.add_argument("--date", help="单天抓取 (YYYY-MM-DD)，等价于 --start=--end")
    p.add_argument("--dry-run", action="store_true", help="只抓取不写本地不发邮件")
    p.add_argument("--no-email", action="store_true", help="跳过邮件发送")
    p.add_argument("--no-local", action="store_true", help="跳过本地存档")
    p.add_argument("--force", action="store_true", help="强制重跑（即使当天已推送）")
    p.add_argument("--config", default=str(SCRIPT_DIR.parent / "config" / "config.json"),
                   help="配置文件路径")
    return p.parse_args()


def parse_date_arg(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        print(f"ERROR: 日期格式不正确，应为 YYYY-MM-DD: {s}")
        sys.exit(1)


def build_date_range(args) -> list[date]:
    """根据命令行参数确定要抓取的日期范围（闭区间）。"""
    today = date.today()
    if args.date:
        d = parse_date_arg(args.date)
        return [d]
    start = parse_date_arg(args.start) if args.start else today
    end = parse_date_arg(args.end) if args.end else start
    if start > end:
        start, end = end, start  # 允许前后颠倒，自动纠正
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def _article_key(a):
    """文章唯一标识，用于增量对比。优先 id，其次 url，最后 title。"""
    return a.get("id") or a.get("url") or a.get("title") or ""


def _load_existing_keys(json_path):
    """读取已存档 articles.json 的文章键集合；不存在则返回空集合。"""
    if not json_path.exists():
        return set()
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            old = json.load(f)
        return {_article_key(a) for a in old if _article_key(a)}
    except Exception:
        return set()


def run_one_day(config, target_date, args):
    """抓取并处理单个日期，返回 (articles, 是否已跳过)。

    增量逻辑：对比已存档 articles.json，只有「有新增文章」时才发邮件；
    文章无变化（重复点现场抓取）则只更新本地文件、不发邮件。
    """
    target_date_str = target_date.strftime("%Y-%m-%d")
    day_folder = f"{target_date.year}.{target_date.month}.{target_date.day}"
    base_dir = Path(config["output"]["local_dir"])
    day_dir = base_dir / day_folder
    json_path = day_dir / "articles.json"

    # 幂等检查：当天已推送过则跳过（除非 --force 或 --dry-run）
    if not args.force and not args.dry_run:
        html_file = day_dir / f"{day_folder}.html"
        md_file = day_dir / f"{day_folder}.md"
        if html_file.exists() and md_file.exists():
            print(f"[skip] {target_date_str} 已推送过（{day_dir} 已存在），跳过")
            return None, True

    print("\n" + "=" * 50)
    print(f"抓取日期: {target_date_str}")
    print("=" * 50)

    # 1. 抓取
    print("\n[1/4] 抓取文章 ...")
    articles = fetch_daily(config, target_date)
    # 1.1 抓取期刊论文（直连 RSS，与公众号写入同一存档）
    try:
        journal_articles = fetch_journals_daily(config, target_date)
        if journal_articles:
            articles.extend(journal_articles)
            print(f"[1/4] 公众号 {len(articles) - len(journal_articles)} 篇 + 期刊 {len(journal_articles)} 篇")
    except Exception as e:
        print(f"[1/4] 期刊抓取异常（已忽略，不影响公众号）: {e}")
    if not articles:
        print(f"{target_date_str} 没有文章，跳过。")
        return [], False

    # 1.5 增量对比：判断是否有新文章（相对已存档）
    existing_keys = _load_existing_keys(json_path)
    new_keys = {_article_key(a) for a in articles if _article_key(a)}
    has_new = bool(new_keys - existing_keys)
    if not has_new and existing_keys:
        print(f"[no-new] {target_date_str} 无新文章（与已存档一致），跳过邮件发送")

    # 2. 渲染
    print("\n[2/4] 渲染 HTML 和 Markdown ...")
    render_cfg = config.get("render", {})
    html = render_html(
        articles, target_date_str,
        group_by_account=render_cfg.get("group_by_account", True),
        sort_desc=render_cfg.get("sort_desc", True),
        include_toc=render_cfg.get("include_toc", True),
    )
    md = render_markdown(
        articles, target_date_str,
        group_by_account=render_cfg.get("group_by_account", True),
        sort_desc=render_cfg.get("sort_desc", True),
    )

    # 3. 保存本地（无论有无新文章，都更新文件，保证本地/Web 内容最新）
    html_path = None
    md_path = None
    if not args.no_local and not args.dry_run:
        print("\n[3/4] 保存到本地 ...")
        day_dir.mkdir(parents=True, exist_ok=True)
        html_path = day_dir / f"{day_folder}.html"
        md_path = day_dir / f"{day_folder}.md"
        html_path.write_text(html, encoding="utf-8")
        md_path.write_text(md, encoding="utf-8")
        json_path.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  - {html_path}")
        print(f"  - {md_path}")
        print(f"  - {json_path}")

    # 4. 邮件（仅当有新增文章时才发）
    if has_new and not args.no_email and not args.dry_run:
        print("\n[4/4] 发送邮件 ...")
        subject = f"{config['email'].get('subject_prefix', '')}{target_date_str} 论文推送（共 {len(articles)} 篇）"
        try:
            send_email(config, subject, html, html_path, md_path)
        except Exception as e:
            print(f"[email] ERROR: 邮件发送失败: {e}")
            print("[email] 本地文件已保存，邮件可稍后重发")
    elif not has_new and not args.no_email and not args.dry_run:
        print(f"\n[4/4] {target_date_str} 无新文章，不发送邮件")

    return articles, False


def main():
    args = parse_args()
    config = load_config(args.config)
    dates = build_date_range(args)

    print("=" * 50)
    print("每日论文推送（公众号 + 期刊）")
    print(f"待抓取日期: {[d.strftime('%Y-%m-%d') for d in dates]}")
    if args.dry_run:
        print("模式: DRY RUN")
    print("=" * 50)

    total_articles = 0
    for d in dates:
        articles, skipped = run_one_day(config, d, args)
        if not skipped and articles is not None:
            total_articles += len(articles)

    print("\n" + "=" * 50)
    print(f"完成，共处理 {len(dates)} 个日期，累计 {total_articles} 篇文章")
    print("=" * 50)


if __name__ == "__main__":
    main()
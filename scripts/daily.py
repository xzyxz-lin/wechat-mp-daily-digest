"""
主入口：抓取 -> 渲染 -> 保存本地 -> 发送邮件。
命令行参数：
  --date 2026-08-13   指定日期（默认今天）
  --dry-run           只抓取不写本地不发邮件
  --no-email          跳过邮件
  --no-local          跳过本地存档
  --force             强制重跑（即使当天已推送）
  --config <path>     指定配置文件
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from fetch_articles import load_config, fetch_daily
from render import render_html, render_markdown
from send_email import send_email


def parse_args():
    p = argparse.ArgumentParser(description="公众号每日论文推送")
    p.add_argument("--date", help="指定日期 (YYYY-MM-DD)，默认今天")
    p.add_argument("--dry-run", action="store_true", help="只抓取不写本地不发邮件")
    p.add_argument("--no-email", action="store_true", help="跳过邮件发送")
    p.add_argument("--no-local", action="store_true", help="跳过本地存档")
    p.add_argument("--force", action="store_true", help="强制重跑（即使当天已推送）")
    p.add_argument("--config", default=str(SCRIPT_DIR.parent / "config" / "config.json"),
                   help="配置文件路径")
    return p.parse_args()


def main():
    args = parse_args()

    target_date = date.today()
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"ERROR: 日期格式不正确，应为 YYYY-MM-DD: {args.date}")
            sys.exit(1)
    target_date_str = target_date.strftime("%Y-%m-%d")
    # 按日期建子文件夹，命名格式：2026.8.13（月/日不带前导零）
    day_folder = f"{target_date.year}.{target_date.month}.{target_date.day}"

    config = load_config(args.config)
    render_cfg = config.get("render", {})

    print("=" * 50)
    print("公众号每日论文推送")
    print(f"日期: {target_date_str}")
    if args.dry_run:
        print("模式: DRY RUN")
    print("=" * 50)

    # 0. 幂等检查：当天已推送过则跳过（除非 --force 或 --dry-run）
    if not args.force and not args.dry_run:
        base_dir = Path(config["output"]["local_dir"])
        day_dir = base_dir / day_folder
        html_file = day_dir / f"{day_folder}.html"
        md_file = day_dir / f"{day_folder}.md"
        if html_file.exists() and md_file.exists():
            print(f"[skip] {target_date_str} 已推送过（{day_dir} 已存在），跳过")
            print("如需重跑请加 --force")
            return

    # 1. 抓取
    print("\n[1/4] 抓取文章 ...")
    articles = fetch_daily(config, target_date)
    if not articles:
        print("今天没有新文章，结束。")
        return

    # 2. 渲染
    print("\n[2/4] 渲染 HTML 和 Markdown ...")
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

    # 3. 保存本地
    html_path = None
    md_path = None
    if not args.no_local and not args.dry_run:
        print("\n[3/4] 保存到本地 ...")
        base_dir = Path(config["output"]["local_dir"])
        # 按日期建子文件夹，命名格式：2026.8.13（月/日不带前导零）
        day_folder = f"{target_date.year}.{target_date.month}.{target_date.day}"
        day_dir = base_dir / day_folder
        day_dir.mkdir(parents=True, exist_ok=True)
        html_path = day_dir / f"{day_folder}.html"
        md_path = day_dir / f"{day_folder}.md"
        json_path = day_dir / "articles.json"
        html_path.write_text(html, encoding="utf-8")
        md_path.write_text(md, encoding="utf-8")
        # 额外存一份结构化数据，供 Web 管理系统检索
        json_path.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  - {html_path}")
        print(f"  - {md_path}")
        print(f"  - {json_path}")

    # 4. 邮件
    if not args.no_email and not args.dry_run:
        print("\n[4/4] 发送邮件 ...")
        subject = f"{config['email'].get('subject_prefix', '')}{target_date_str} 公众号推送（共 {len(articles)} 篇）"
        try:
            send_email(config, subject, html, html_path, md_path)
        except Exception as e:
            print(f"[email] ERROR: 邮件发送失败: {e}")
            print("[email] 本地文件已保存，邮件可稍后重发")

    print("\n" + "=" * 50)
    print("完成")
    print("=" * 50)


if __name__ == "__main__":
    main()
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "web"))

import daily
import fetch_articles
import fetch_journals
import paper_observatory


class DailyMergeTests(unittest.TestCase):
    def test_merge_preserves_existing_and_adds_only_new_articles(self):
        existing = [
            {"id": "old-1", "title": "旧标题", "kept": "保留字段"},
            {"id": "old-2", "title": "第二篇"},
        ]
        fetched = [
            {"id": "old-1", "title": "更新标题"},
            {"id": "new-3", "title": "新增论文"},
        ]

        merged = daily._merge_articles(existing, fetched)

        self.assertEqual([item["id"] for item in merged], ["old-1", "old-2", "new-3"])
        self.assertEqual(merged[0]["title"], "更新标题")
        self.assertEqual(merged[0]["kept"], "保留字段")

    def test_run_one_day_keeps_archive_when_mp_source_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            day_dir = base / "2026.8.20"
            day_dir.mkdir()
            (day_dir / "articles.json").write_text(
                json.dumps([{"id": "old", "title": "旧论文", "category": "期刊"}], ensure_ascii=False),
                encoding="utf-8",
            )
            args = SimpleNamespace(force=True, dry_run=False, no_local=False, no_email=True)
            config = {"output": {"local_dir": str(base)}, "render": {}}

            with (
                patch.object(daily, "fetch_daily", side_effect=RuntimeError("WeWe 登录失效")),
                patch.object(daily, "fetch_journals_daily", return_value=[
                    {"id": "new", "title": "Nature 新论文", "category": "期刊"}
                ]),
                patch.object(daily, "render_html", return_value="<html></html>"),
                patch.object(daily, "render_markdown", return_value="# digest"),
            ):
                articles, skipped = daily.run_one_day(config, date(2026, 8, 20), args)

            saved = json.loads((day_dir / "articles.json").read_text(encoding="utf-8"))
            self.assertFalse(skipped)
            self.assertEqual(len(articles), 2)
            self.assertEqual({item["id"] for item in saved}, {"old", "new"})

    def test_invalid_existing_archive_stops_before_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "articles.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "保护数据"):
                daily._load_existing_articles(path)

    def test_successful_empty_fetch_writes_an_empty_daily_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            args = SimpleNamespace(force=True, dry_run=False, no_local=False, no_email=True)
            config = {"output": {"local_dir": str(base)}, "render": {}}
            with (
                patch.object(daily, "fetch_daily", return_value=[]),
                patch.object(daily, "fetch_journals_daily", return_value=[]),
                patch.object(daily, "render_html", return_value="<html></html>"),
                patch.object(daily, "render_markdown", return_value="# empty"),
            ):
                articles, skipped = daily.run_one_day(config, date(2026, 8, 20), args)

            saved_path = base / "2026.8.20" / "articles.json"
            self.assertFalse(skipped)
            self.assertEqual(articles, [])
            self.assertEqual(json.loads(saved_path.read_text(encoding="utf-8")), [])


class SourceTests(unittest.TestCase):
    def test_local_wewe_session_ignores_environment_proxy(self):
        self.assertFalse(fetch_articles._local_session("http://localhost:4000").trust_env)
        self.assertTrue(fetch_articles._local_session("https://example.com").trust_env)

    def test_month_only_date_is_parsed_and_future_date_is_not_current(self):
        parsed = fetch_journals._parse_date("October 2026")
        self.assertEqual((parsed.year, parsed.month, parsed.day), (2026, 10, 1))
        self.assertGreater(fetch_journals._local_date(parsed), date(2026, 8, 20))

    def test_crossref_created_date_can_backfill_future_issue_rss(self):
        parsed = fetch_journals._crossref_created_date({
            "created": {"date-parts": [[2026, 8, 20]]},
            "published-print": {"date-parts": [[2026, 10]]},
        })
        self.assertEqual(fetch_journals._local_date(parsed), date(2026, 8, 20))

    def test_seen_archive_dates_are_sorted_as_dates_not_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            (root / "config").mkdir()
            (root / "config" / "config.json").write_text(
                json.dumps({"output": {"local_dir": str(archive)}}), encoding="utf-8"
            )
            for folder, title in (("2026.8.9", "九号论文"), ("2026.8.20", "二十号论文")):
                day_dir = archive / folder
                day_dir.mkdir(parents=True)
                (day_dir / "articles.json").write_text(
                    json.dumps([{"title": title}], ensure_ascii=False), encoding="utf-8"
                )
            with patch.object(fetch_journals, "PROJECT_DIR", root):
                seen = fetch_journals._load_seen_urls(date(2026, 8, 20))

            self.assertIn("九号论文", seen)
            self.assertIn("二十号论文", seen)


class SnapshotTests(unittest.TestCase):
    def test_archive_date_is_auto_added_to_snapshot_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            day_dir = archive / "2026.8.20"
            day_dir.mkdir(parents=True)
            (day_dir / "articles.json").write_text(
                json.dumps([
                    {"id": "mp", "account": "膜法笔记", "category": "公众号"},
                    {"id": "jnl", "account": "Nature", "category": "期刊"},
                ], ensure_ascii=False),
                encoding="utf-8",
            )
            with (
                patch.object(paper_observatory, "ARCHIVE_DIR", archive),
                patch.object(paper_observatory, "SNAPSHOTS_PATH", root / "snapshots.json"),
                patch.object(paper_observatory, "FUNDS_PATH", root / "funds.json"),
            ):
                snapshots = paper_observatory.sync_snapshots_from_archive()

            self.assertIn("2026.8.20", snapshots)
            self.assertEqual(snapshots["2026.8.20"]["mp_count"], 1)
            self.assertEqual(snapshots["2026.8.20"]["journal_count"], 1)

    def test_custom_fetch_uses_requested_snapshot_dates(self):
        self.assertEqual(
            paper_observatory._snapshot_dates_for_fetch("2026-08-19", "2026-08-20"),
            ["2026.8.19", "2026.8.20"],
        )


if __name__ == "__main__":
    unittest.main()

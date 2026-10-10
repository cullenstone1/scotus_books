"""What daily publishes: all new releases first, else one from queue.txt, else backfill."""
from datetime import date, datetime, timedelta, timezone

import pytest

from scotus import catalog, cli


def _row(key, days_ago, **extra):
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    term, rnum = key.split("-")
    return {"key": key, "term": int(term), "rnum": rnum, "date": d, "docket": f"D{key}", "name": f"Case {key}",
            "author": "R", "citation": "", "summary": "", "pdf_url": f"https://x/{key}.pdf", "revisions": "[]", **extra}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "QUEUE", tmp_path / "queue.txt")
    db = catalog.connect(tmp_path / "catalog.db")
    for key, days in [("25-1", 300), ("25-2", 200), ("25-3", 3), ("25-4", 1), ("25-5", 1)]:
        catalog.upsert(db, _row(key, days))
    db.commit()
    return db


def test_new_releases_are_recent_unuploaded_oldest_first(db):
    assert [r["key"] for r in cli.new_releases(db)] == ["25-3", "25-4", "25-5"]
    catalog.mark(db, "25-4", uploaded=catalog.now())
    assert [r["key"] for r in cli.new_releases(db)] == ["25-3", "25-5"]


def test_backlog_prefers_queue_then_newest(db):
    assert cli.pick_backlog(db)[0]["key"] == "25-5"          # newest unuploaded
    cli.QUEUE.write_text("25-1  # first pick\n25-2\n")
    assert cli.pick_backlog(db)[0]["key"] == "25-1"
    catalog.mark(db, "25-1", uploaded=catalog.now())
    assert cli.pick_backlog(db)[0]["key"] == "25-2"           # uploaded queue entries are skipped


def test_failed_opinions_are_skipped(db):
    catalog.mark(db, "25-3", failures=cli.MAX_FAILURES)
    assert [r["key"] for r in cli.new_releases(db)] == ["25-4", "25-5"]


def test_pick_next_puts_new_releases_before_queue(db):
    cli.QUEUE.write_text("25-1\n")
    row, why = cli.pick_next(db)
    assert (row["key"], why) == ("25-3", "new release")


def test_uploads_today_counts_from_pacific_midnight(db):
    catalog.mark(db, "25-1", uploaded=catalog.now())
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
    catalog.mark(db, "25-2", uploaded=yesterday)
    assert cli.uploads_today(db) == 1

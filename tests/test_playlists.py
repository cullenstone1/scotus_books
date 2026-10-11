"""Which playlists a video goes in, where in them, and how much quota playlist work may spend."""
import pytest

from scotus import catalog, cli, playlists
from scotus.catalog import now

from test_policy import _row


def _doc(*titles):
    kinds = {"Syllabus": "syllabus", "PER CURIAM.": "per_curiam"}
    return {"sections": [{"kind": kinds.get(t, "majority" if "delivered" in t else "dissent"), "title": t}
                         for t in titles]}


def test_term_justices_and_per_curiam():
    row = {"term": 25}
    doc = _doc("Syllabus", "CHIEF JUSTICE ROBERTS delivered the opinion of the Court.",
               "JUSTICE JACKSON, with whom JUSTICE SOTOMAYOR joins, dissenting.", "JUSTICE JACKSON, dissenting.")
    got = {name: title for name, title, *_ in playlists.playlists_for(row, doc)}
    assert got == {"term:25": "October Term 2025 Opinions",
                   "justice:roberts": "Opinions by Chief Justice John G. Roberts, Jr.",
                   "justice:jackson": "Opinions by Justice Ketanji Brown Jackson"}   # joiners don't count
    pc = playlists.playlists_for(row, _doc("PER CURIAM.", "JUSTICE KAGAN, dissenting."))
    assert [p[0] for p in pc] == ["term:25", "per_curiam", "justice:kagan"]


class FakeClient:
    def __init__(self):
        self.calls = []

    def find(self, title):
        return None

    def create(self, title, description):
        self.calls.append(("create", title))
        return f"PL{len(self.calls)}"

    def add(self, playlist_id, video_id, pos):
        self.calls.append(("add", playlist_id, video_id, pos))
        return f"item{len(self.calls)}"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(playlists, "DATA", tmp_path)
    db = catalog.connect(tmp_path / "catalog.db")
    import json
    for key, days in [("25-1", 30), ("25-2", 20), ("25-3", 10)]:
        catalog.upsert(db, _row(key, days, youtube_id=f"v{key}"))
        (tmp_path / "build" / key).mkdir(parents=True)
        (tmp_path / "build" / key / "doc.json").write_text(json.dumps(_doc("PER CURIAM.")))
    db.commit()
    return db


def test_sync_keeps_date_order_and_skips_done(db):
    db.execute("UPDATE opinions SET uploaded = '2000-01-01T00:00:00+00:00'")   # not today: full quota
    # pretend 25-2 was added first (as the newest-first backfill would), then sync the rest
    fake = FakeClient()
    db.execute("UPDATE opinions SET youtube_id = NULL WHERE key != '25-2'")
    assert playlists.sync(db, client=fake) == 0
    db.execute("UPDATE opinions SET youtube_id = 'v' || key")
    fake.calls.clear()
    assert playlists.sync(db, client=fake) == 0
    adds = [(c[1], c[2], c[3]) for c in fake.calls if c[0] == "add"]
    # term playlist is oldest first, per curiam newest first
    assert ("PL1", "v25-1", 0) in adds and ("PL1", "v25-3", 2) in adds
    assert ("PL3", "v25-1", 1) in adds and ("PL3", "v25-3", 0) in adds
    fake.calls.clear()
    assert playlists.sync(db, client=fake) == 0 and fake.calls == []


def test_room_reserves_the_rest_of_todays_uploads(db):
    assert playlists.room(db) == (playlists.DAILY_QUOTA - cli.UPLOADS_PER_DAY * playlists.UPLOAD_COST) // 50
    catalog.mark(db, "25-1", uploaded=now())
    catalog.mark(db, "25-2", uploaded=now())
    assert playlists.room(db) == (playlists.DAILY_QUOTA - cli.UPLOADS_PER_DAY * playlists.UPLOAD_COST) // 50
    fake = FakeClient()
    db.execute("UPDATE opinions SET uploaded = ?", (now(),))   # all 5 uploads used: room is what's left
    for k in ("25-4", "25-5"):
        catalog.upsert(db, _row(k, 1, uploaded=now()))
    left = playlists.sync(db, client=fake)
    assert left == 0
    assert playlists.room(db) == (playlists.DAILY_QUOTA - 5 * playlists.UPLOAD_COST) // 50 - 2 - 6

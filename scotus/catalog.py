"""SQLite catalog: one row per opinion, with a timestamp for each pipeline stage."""
import sqlite3
from datetime import datetime, timezone

from . import DATA

SCHEMA = """
CREATE TABLE IF NOT EXISTS opinions (
  key         TEXT PRIMARY KEY,   -- "{term}-{rnum}", e.g. "23-30"; stable when the PDF url changes
  term        INTEGER NOT NULL,   -- two-digit October Term, e.g. 23 for OT2023
  rnum        TEXT NOT NULL,      -- R- column; "D1" etc. for dissents from denial
  date        TEXT,               -- ISO date released
  docket      TEXT,
  name        TEXT,
  author      TEXT,               -- initials as listed, "PC" = per curiam
  citation    TEXT,
  summary     TEXT,
  pdf_url     TEXT,
  pdf_path    TEXT,
  pdf_sha256  TEXT,
  revisions   TEXT,               -- JSON list of revision urls
  first_seen  TEXT,
  updated     TEXT,
  extracted   TEXT,
  rendered    TEXT,
  uploaded    TEXT,
  youtube_id  TEXT,
  failures    INTEGER DEFAULT 0,  -- build/upload attempts that raised; daily skips after MAX_FAILURES
  last_error  TEXT
);
"""
MIGRATIONS = {   # columns added after the first release; created on old databases by connect()
    "failures": "INTEGER DEFAULT 0",
    "last_error": "TEXT",
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None):
    path = path or DATA / "catalog.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    have = {r["name"] for r in db.execute("PRAGMA table_info(opinions)")}
    for col, decl in MIGRATIONS.items():
        if col not in have:
            db.execute(f"ALTER TABLE opinions ADD COLUMN {col} {decl}")
    db.commit()
    return db


def upsert(db, row):
    """Insert a scraped row, or update it. Returns "new", "changed" or None."""
    old = db.execute("SELECT * FROM opinions WHERE key = ?", (row["key"],)).fetchone()
    if old is None:
        cols = list(row) + ["first_seen", "updated"]
        db.execute(
            f"INSERT INTO opinions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [*row.values(), now(), now()],
        )
        return "new"
    changed = {k: v for k, v in row.items() if old[k] != v}
    if not changed:
        return None
    sets = ", ".join(f"{k} = ?" for k in changed)
    db.execute(f"UPDATE opinions SET {sets}, updated = ? WHERE key = ?", [*changed.values(), now(), row["key"]])
    return "changed"


def mark(db, key, **fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE opinions SET {sets} WHERE key = ?", [*fields.values(), key])
    db.commit()

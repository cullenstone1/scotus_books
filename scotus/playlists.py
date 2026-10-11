"""YouTube playlists: one per October Term, one per Justice, and one for per curiam opinions.

Each uploaded video goes in its term's playlist, in the playlist of every Justice who wrote a section
of it (majority, concurrence or dissent), and in "Per Curiam Opinions" if the Court's opinion is
unsigned. Playlists are created the first time they're needed.

  python -m scotus.playlists              add every uploaded video to the playlists it's missing from
  python -m scotus.playlists --dry-run    show what would be added

Daily runs this after its uploads. Each playlist addition costs 50 quota units, so it only spends
what's left after reserving room for the rest of the day's uploads, and finishes on a later run.
"""
import argparse
import json
import sys
import time

from . import DATA, catalog
from .catalog import now
from .render import justice_title, justices, section_author

DAILY_QUOTA = 10_000   # YouTube's default API quota, in units per day
UPLOAD_COST = 1_650    # videos.insert + thumbnails.set
PLAYLIST_COST = 50     # playlists.insert or playlistItems.insert


def playlists_for(row, doc):
    """[(name, title, description, newest_first)] for one opinion. name is our stable key for a playlist."""
    year = 2000 + row["term"]
    out = [(f"term:{row['term']}", f"October Term {year} Opinions",
            f"Supreme Court opinions from the October Term {year} (decided {year}–{year + 1}), "
            "read aloud in order of decision.", False)]
    sections = doc["sections"]
    if any(s["kind"] == "per_curiam" for s in sections):
        out.append(("per_curiam", "Per Curiam Opinions",
                    "Unsigned Supreme Court opinions issued in the name of the Court, read aloud, newest first.", True))
    names = justices()
    seen = set()
    for s in sections:
        who = section_author(s["title"])
        if not who or who in seen:
            continue
        seen.add(who)
        name = f"{justice_title(s['title'])} {names.get(who, who.title())}"
        out.append((f"justice:{who}", f"Opinions by {name}",
                    f"Supreme Court opinions, concurrences and dissents written by {name}, read aloud, newest first.",
                    True))
    return out


def _doc(key):
    path = DATA / "build" / key / "doc.json"
    return json.loads(path.read_text()) if path.exists() else None


def missing(db):
    """[(row, name, title, description, newest_first)] for uploaded videos not yet in a playlist they belong in,
    oldest decision first."""
    have = {(r["key"], r["playlist"]) for r in db.execute("SELECT key, playlist FROM playlist_items")}
    out = []
    for row in db.execute("SELECT * FROM opinions WHERE youtube_id IS NOT NULL ORDER BY date, rnum"):
        doc = _doc(row["key"])
        if doc is None:
            continue
        out += [(row, *p) for p in playlists_for(row, doc) if (row["key"], p[0]) not in have]
    return out


def position(db, name, row, newest_first):
    """Where the video goes so the playlist stays in date order: the number of items already in it that
    sort before this one."""
    op = ">" if newest_first else "<"
    return db.execute(f"""SELECT count(*) n FROM playlist_items i JOIN opinions o ON o.key = i.key
                          WHERE i.playlist = ? AND (o.date, o.rnum) {op} (?, ?)""",
                      (name, row["date"], row["rnum"])).fetchone()["n"]


def units_used_today(db):
    """Our estimate of today's quota use (since midnight Pacific): uploads plus playlist calls."""
    from .cli import uploads_today, quota_day_start
    since = quota_day_start()
    ops = db.execute("SELECT count(*) n FROM playlist_items WHERE added >= ?", (since,)).fetchone()["n"]
    ops += db.execute("SELECT count(*) n FROM playlists WHERE created >= ?", (since,)).fetchone()["n"]
    return uploads_today(db) * UPLOAD_COST + ops * PLAYLIST_COST


def room(db):
    """Playlist calls we can make now and still leave quota for the rest of today's uploads."""
    from .cli import UPLOADS_PER_DAY, uploads_today
    reserve = max(0, UPLOADS_PER_DAY - uploads_today(db)) * UPLOAD_COST
    return max(0, (DAILY_QUOTA - units_used_today(db) - reserve) // PLAYLIST_COST)


class Client:
    """The few YouTube calls we need, with our playlists looked up once per run."""

    def __init__(self):
        from googleapiclient.discovery import build
        from .upload import credentials
        self.yt = build("youtube", "v3", credentials=credentials())
        self._existing = None

    def _call(self, req):
        """Execute, retrying YouTube's transient errors (a playlist that was just created often answers
        409 SERVICE_UNAVAILABLE for a few seconds)."""
        from googleapiclient.errors import HttpError
        from .upload import QuotaExceeded, _quota_error
        for wait in (2, 5, 15, 30, None):
            try:
                return req.execute()
            except HttpError as e:
                if _quota_error(e):
                    raise QuotaExceeded(str(e)) from e
                if wait is None or e.resp.status not in (409, 500, 503):
                    raise
                time.sleep(wait)

    def find(self, title):
        """Our channel's playlist with this title, if one exists (so a lost database doesn't make duplicates)."""
        if self._existing is None:
            self._existing, token = {}, None
            while True:
                resp = self._call(self.yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=token))
                self._existing.update({p["snippet"]["title"]: p["id"] for p in resp.get("items", [])})
                token = resp.get("nextPageToken")
                if not token:
                    break
        return self._existing.get(title)

    def create(self, title, description):
        body = {"snippet": {"title": title, "description": description, "defaultLanguage": "en"},
                "status": {"privacyStatus": "public"}}
        return self._call(self.yt.playlists().insert(part="snippet,status", body=body))["id"]

    def add(self, playlist_id, video_id, pos):
        from googleapiclient.errors import HttpError
        body = {"snippet": {"playlistId": playlist_id, "position": pos,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
        try:
            return self._call(self.yt.playlistItems().insert(part="snippet", body=body))["id"]
        except HttpError as e:
            if "position" not in str(e).lower():
                raise
            del body["snippet"]["position"]   # the playlist was edited by hand; append instead
            return self._call(self.yt.playlistItems().insert(part="snippet", body=body))["id"]


def sync(db, dry_run=False, client=None):
    """Add uploaded videos to the playlists they're missing from, within today's spare quota.
    Returns the number of additions left for a later run."""
    from .upload import QuotaExceeded
    todo = missing(db)
    if not todo:
        print("playlists up to date")
        return 0
    if dry_run:
        for row, name, title, *_ in todo:
            print(f"would add {row['key']} {row['name']} to {title!r}")
        return len(todo)
    client = client or Client()
    done = 0
    try:
        for row, name, title, description, newest_first in todo:
            pl = db.execute("SELECT * FROM playlists WHERE name = ?", (name,)).fetchone()
            if pl is None:
                if room(db) < 2:
                    break
                playlist_id = client.find(title)
                created = None
                if playlist_id is None:
                    playlist_id, created = client.create(title, description), now()
                    print(f"created playlist {title!r}: https://www.youtube.com/playlist?list={playlist_id}")
                db.execute("INSERT INTO playlists (name, title, playlist_id, created) VALUES (?, ?, ?, ?)",
                           (name, title, playlist_id, created))
                db.commit()
                pl = db.execute("SELECT * FROM playlists WHERE name = ?", (name,)).fetchone()
            if room(db) < 1:
                break
            item_id = client.add(pl["playlist_id"], row["youtube_id"], position(db, name, row, newest_first))
            db.execute("INSERT INTO playlist_items (key, playlist, item_id, added) VALUES (?, ?, ?, ?)",
                       (row["key"], name, item_id, now()))
            db.commit()
            done += 1
            print(f"added {row['key']} {row['name']} to {title!r}")
    except QuotaExceeded as e:
        print(f"YouTube quota used up; playlists finish on a later run ({e})", file=sys.stderr)
    left = len(todo) - done
    if left:
        print(f"{left} playlist addition(s) left for a later run")
    return left


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    sync(catalog.connect(), args.dry_run)


if __name__ == "__main__":
    main()

"""scotus_books command line.

  python -m scotus.cli scrape [TERM ...]       update the catalog from supremecourt.gov (default: current + previous term)
  python -m scotus.cli status                  what's in the catalog and what's been done
  python -m scotus.cli review KEY              extract + clean, write the review report (data/review/)
  python -m scotus.cli build KEY               full pipeline for one opinion: PDF -> audio -> video (no upload)
  python -m scotus.cli next [--dry-run]        build and upload one opinion (new release > queue.txt > backfill)
  python -m scotus.cli daily [--new-only]      what the timers run: scrape, publish all new releases (up to
                                               the upload budget), else one from queue.txt / backfill (unless
                                               --new-only); then refresh the website's opinions page
  python -m scotus.cli queue add KEY ...       add opinions to queue.txt; also: queue list, queue remove KEY
  python -m scotus.cli retry KEY               clear an opinion's failure count so daily tries it again

KEY is the catalog key "{term}-{R number}", e.g. 25-64; a docket number like 25-112 also works.
"""
import argparse
import fcntl
import json
import sys
import traceback
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from . import DATA, ROOT, catalog, scrape
from .catalog import now

QUEUE = ROOT / "queue.txt"
MAX_FAILURES = 2        # after this many failed attempts, daily skips an opinion until `retry`
OLDEST_TERM = 18        # supremecourt.gov term pages go back to OT2018
NEW_RELEASE_DAYS = 14   # opinions released this recently jump ahead of the queue
UPLOADS_PER_DAY = 6     # YouTube's default quota: 10,000 units/day; an upload + thumbnail costs 1,650
QUOTA_TZ = ZoneInfo("America/Los_Angeles")   # the YouTube quota day starts at midnight Pacific


def current_term(today=None):
    today = today or date.today()
    return (today.year - 2000) if today.month >= 10 else (today.year - 2001)


def find(db, ref):
    row = db.execute("SELECT * FROM opinions WHERE key = ?", (ref,)).fetchone()
    if row is None:
        rows = db.execute("SELECT * FROM opinions WHERE lower(docket) = lower(?) ORDER BY date DESC", (ref,)).fetchall()
        if len(rows) > 1:
            sys.exit(f"{ref} matches several opinions: {', '.join(r['key'] for r in rows)}; use a key")
        row = rows[0] if rows else None
    if row is None:
        sys.exit(f"no opinion {ref!r} in the catalog (try `scrape` first)")
    return row


def pretty_date(iso):
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{d:%B} {d.day}, {d.year}"


def author_line(doc):
    for sec in doc["sections"]:
        if sec["kind"] == "per_curiam":
            return "Per Curiam"
        if sec["kind"] in ("majority", "plurality"):
            from .speak import speakable
            name = speakable(sec["title"]).split(" delivered")[0].split(" announced")[0]
            return f"Opinion of the Court by {name}" if sec["kind"] == "majority" else f"Lead opinion by {name}"
    return ""


def cmd_scrape(args, db):
    terms = args.terms or [current_term(), current_term() - 1]
    for t in terms:
        new, changed = scrape.scrape_term(db, int(t))
        print(f"OT20{int(t):02d}: {new} new, {changed} changed")


def cmd_status(args, db):
    for r in db.execute("""SELECT term, count(*) n, count(extracted) x, count(rendered) r, count(uploaded) u
                           FROM opinions GROUP BY term ORDER BY term DESC"""):
        print(f"OT20{r['term']:02d}: {r['n']:3d} opinions, {r['x']:3d} extracted, {r['r']:3d} rendered, {r['u']:3d} uploaded")
    print(f"uploads today (since midnight Pacific): {uploads_today(db)} of {UPLOADS_PER_DAY}")
    releases = new_releases(db)
    if releases:
        print(f"new releases waiting: {', '.join(r['key'] for r in releases)}")
    pending = [r for r in queue_refs() if not _uploaded(db, r)]
    print(f"queue.txt: {len(pending)} waiting")
    for r in db.execute("SELECT key, name, failures, last_error FROM opinions WHERE failures >= ? ORDER BY key",
                        (MAX_FAILURES,)):
        print(f"skipped after {r['failures']} failures: {r['key']} {r['name']}: {r['last_error']}")
    row, why = pick_next(db)
    if row is not None:
        print(f"next: {row['key']} {row['name']} ({row['date']}) [{why}]")


def cmd_review(args, db):
    from .review import review
    row = find(db, args.ref)
    pdf = scrape.download(db, row)
    review(pdf, DATA / "review")
    print(f"wrote {DATA / 'review' / pdf.stem}.html and .review.txt")


def build(db, row, voice="am_michael", model=None):
    from .clean import clean_doc
    from .extract import extract
    from .render import section_card, slideshow, title_card
    from .review import review
    from . import tts
    from .speak import speakable

    pdf = scrape.download(db, row)
    out = DATA / "build" / row["key"]
    out.mkdir(parents=True, exist_ok=True)
    doc = review(pdf, DATA / "review")         # also writes the review report
    if not doc["sections"]:
        raise RuntimeError(f"no sections found in {pdf}")
    (out / "doc.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    catalog.mark(db, row["key"], extracted=now())

    when = pretty_date(row["date"])
    items = tts.script(doc, row["name"], when)
    (out / "script.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    synth = tts.Synth(model, voice)
    model = synth.model
    chapters = tts.render(items, synth, out / "reading.wav",
                          log=lambda *a, **k: print(*a, **k, file=sys.stderr, flush=True))
    tts.encode(out / "reading.wav", out / "reading.m4a")
    (out / "reading.wav").unlink()
    (out / "chapters.txt").write_text(tts.chapters_text(chapters) + "\n")

    title_card(out / "card.png", row["name"], [f"No. {row['docket']} · Decided {when}", author_line(doc)])
    # one card per chapter: chapter 0 is the introduction, then one per section in order
    cards = [(out / "card.png", chapters[0][1])]
    for i, (sec, (_, start)) in enumerate(zip(doc["sections"], chapters[1:]), 1):
        png = section_card(out / f"card{i}.png", row["name"], sec["kind"], sec["title"], speakable(sec["title"]))
        cards.append((png, start))
    slideshow(cards, out / "reading.m4a", out / "video.mp4")
    meta = {
        "key": row["key"], "name": row["name"], "docket": row["docket"], "date": row["date"],
        "summary": row["summary"], "pdf_url": row["pdf_url"], "chapters": tts.chapters_text(chapters),
        "author": author_line(doc), "voice": voice, "model": model,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    catalog.mark(db, row["key"], rendered=now())
    return out


def cmd_build(args, db):
    row = find(db, args.ref)
    out = build(db, row, args.voice, args.model)
    print(f"built {row['key']} {row['name']} -> {out}")


def queue_refs():
    """Entries in queue.txt, in order. One key or docket per line; # starts a comment."""
    if not QUEUE.exists():
        return []
    return [l.split("#")[0].strip() for l in QUEUE.read_text().splitlines() if l.split("#")[0].strip()]


def _uploaded(db, ref):
    row = db.execute("SELECT uploaded FROM opinions WHERE key = ? OR lower(docket) = lower(?)", (ref, ref)).fetchone()
    return row is not None and row["uploaded"] is not None


OK = "uploaded IS NULL AND coalesce(failures, 0) < ?"


def new_releases(db):
    """Recent opinions not yet uploaded, oldest first. Daily publishes all of these."""
    return db.execute(f"""SELECT * FROM opinions WHERE {OK} AND date >= date('now', ?)
                          ORDER BY date, rnum""", (MAX_FAILURES, f"-{NEW_RELEASE_DAYS} days")).fetchall()


def pick_backlog(db):
    """One opinion from queue.txt (in order), else backfill (newest first)."""
    for ref in queue_refs():
        row = db.execute(f"SELECT * FROM opinions WHERE (key = ? OR lower(docket) = lower(?)) AND {OK}",
                         (ref, ref, MAX_FAILURES)).fetchone()
        if row:
            return row, "queue.txt"
    row = db.execute(f"SELECT * FROM opinions WHERE {OK} ORDER BY date DESC, rnum DESC", (MAX_FAILURES,)).fetchone()
    return row, "backfill"


def pick_next(db):
    """What to publish next: recent releases first, then queue.txt in order, then backfill (newest first).
    Skips anything already uploaded and anything that has failed MAX_FAILURES times."""
    releases = new_releases(db)
    if releases:
        return releases[0], "new release"
    return pick_backlog(db)


def uploads_today(db):
    """Uploads since midnight Pacific, when YouTube's daily quota resets."""
    start = datetime.now(QUOTA_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    since = start.astimezone(timezone.utc).isoformat(timespec="seconds")
    return db.execute("SELECT count(*) n FROM opinions WHERE uploaded >= ?", (since,)).fetchone()["n"]


def publish(db, row, privacy, voice="am_michael", model=None):
    """Build (unless already built) and upload one opinion. Records failures instead of raising,
    except QuotaExceeded, which isn't the opinion's fault and stops the run."""
    from .upload import QuotaExceeded, upload
    out = DATA / "build" / row["key"]
    try:
        if not (row["rendered"] and (out / "video.mp4").exists() and (out / "meta.json").exists()):
            out = build(db, row, voice, model)
        video_id = upload(out, privacy)
    except QuotaExceeded as e:
        catalog.mark(db, row["key"], last_error=f"QuotaExceeded: {e}"[:500])
        raise
    except Exception as e:
        catalog.mark(db, row["key"], failures=(row["failures"] or 0) + 1, last_error=f"{type(e).__name__}: {e}"[:500])
        traceback.print_exc()
        return None
    catalog.mark(db, row["key"], uploaded=now(), youtube_id=video_id, last_error=None)
    return video_id


def _publish_and_report(db, row, why, args):
    """Publish one opinion and print the result. Returns True on success."""
    print(f"next: {row['key']} {row['name']} ({row['date']}) [{why}]", flush=True)
    if args.dry_run:
        return True
    video_id = publish(db, row, args.privacy, args.voice, args.model)
    if video_id is None:
        print(f"FAILED: {row['key']} {row['name']}", file=sys.stderr, flush=True)
        return False
    print(f"uploaded {row['key']} ({args.privacy}): https://youtu.be/{video_id}", flush=True)
    return True


def cmd_next(args, db):
    """Publish exactly one opinion, by the same priority daily uses."""
    from .upload import QuotaExceeded
    row, why = pick_next(db)
    if row is None:
        print("nothing left to publish")
        return 0
    try:
        return 0 if _publish_and_report(db, row, why, args) else 1
    except QuotaExceeded as e:
        print(f"YouTube quota used up; try again after midnight Pacific ({e})", file=sys.stderr)
        return 1


def cmd_daily(args, db):
    """Scrape, then publish every new release (up to the day's upload budget); on a day with no new
    releases, publish one opinion from queue.txt or the backfill (unless --new-only). Then refresh the
    opinions page on the website. Holds a lock so runs can't overlap."""
    lock = open(DATA / "daily.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another daily run is in progress; exiting")
        return 0
    print(f"=== {'evening' if args.new_only else 'daily'} run {datetime.now().isoformat(timespec='seconds')} ===",
          flush=True)
    rc = _daily(args, db)
    if not args.dry_run:
        try:
            from . import site
            site.write(db)
            site.push()
        except Exception:
            traceback.print_exc()   # a stale web page shouldn't fail the run
    return rc


def _daily(args, db):
    from .upload import QuotaExceeded
    args.terms = []
    try:
        cmd_scrape(args, db)
    except Exception:
        traceback.print_exc()   # the site being down shouldn't stop us publishing from the backlog

    budget = UPLOADS_PER_DAY - uploads_today(db)
    if budget <= 0:
        print(f"already uploaded {UPLOADS_PER_DAY} today; nothing more until midnight Pacific")
        return 0
    releases = new_releases(db)
    failed = False
    try:
        if releases:
            print(f"{len(releases)} new release(s); upload budget today: {budget}", flush=True)
            for row in releases[:budget]:
                failed |= not _publish_and_report(db, row, "new release", args)
            for row in releases[budget:]:
                print(f"carried over to tomorrow: {row['key']} {row['name']}")
            return 1 if failed else 0
        if args.new_only:
            print("no new releases")
            return 0
        # no new releases: one from the queue or backfill; reach one term further back when it runs dry
        row, why = pick_backlog(db)
        while row is None:
            oldest = db.execute("SELECT min(term) t FROM opinions").fetchone()["t"]
            if oldest is None or oldest <= OLDEST_TERM:
                print("nothing left to publish")
                return 0
            args.terms = [oldest - 1]
            cmd_scrape(args, db)
            row, why = pick_backlog(db)
        return 0 if _publish_and_report(db, row, why, args) else 1
    except QuotaExceeded as e:
        print(f"YouTube quota used up; the rest go out tomorrow ({e})", file=sys.stderr)
        return 1


def cmd_retry(args, db):
    row = find(db, args.ref)
    catalog.mark(db, row["key"], failures=0, last_error=None)
    print(f"cleared failures for {row['key']} {row['name']}")
    return 0


def cmd_queue(args, db):
    if args.action == "list":
        refs = queue_refs()
        if not refs:
            print("queue.txt is empty")
        for ref in refs:
            row = db.execute("SELECT * FROM opinions WHERE key = ? OR lower(docket) = lower(?)", (ref, ref)).fetchone()
            state = "not in catalog" if row is None else ("uploaded" if row["uploaded"] else "waiting")
            print(f"{ref:10} {state:15} {row['name'] if row else ''}")
        return 0
    if not args.refs:
        sys.exit("give at least one KEY or docket")
    if args.action == "add":
        with QUEUE.open("a") as f:
            for ref in args.refs:
                row = find(db, ref)
                f.write(f"{row['key']}  # {row['name']} ({row['date']})\n")
                print(f"queued {row['key']} {row['name']}")
    elif args.action == "remove":
        keys = {find(db, r)["key"] for r in args.refs}
        lines = QUEUE.read_text().splitlines() if QUEUE.exists() else []
        kept = [l for l in lines if l.split("#")[0].strip() not in keys]
        QUEUE.write_text("\n".join(kept) + ("\n" if kept else ""))
        print(f"removed {len(lines) - len(kept)} line(s)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scotus", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scrape"); p.add_argument("terms", nargs="*")
    sub.add_parser("status")
    p = sub.add_parser("review"); p.add_argument("ref")
    for name in ("build", "next", "daily"):
        p = sub.add_parser(name)
        if name == "build":
            p.add_argument("ref")
        else:
            p.add_argument("--dry-run", action="store_true")
            if name == "daily":
                p.add_argument("--new-only", action="store_true",
                               help="publish only new releases, never the queue or backfill (the evening run)")
            p.add_argument("--privacy", default="public", choices=["private", "unlisted", "public"],
                           help="YouTube visibility for uploads (default public; the timers pass their own setting)")
        p.add_argument("--voice", default="am_michael")
        p.add_argument("--model", help="default: full model on GPU, int8 on CPU")
    p = sub.add_parser("queue")
    p.add_argument("action", choices=["add", "list", "remove"])
    p.add_argument("refs", nargs="*")
    p = sub.add_parser("retry"); p.add_argument("ref")
    args = ap.parse_args(argv)
    db = catalog.connect()
    handler = {"scrape": cmd_scrape, "status": cmd_status, "review": cmd_review, "build": cmd_build,
               "next": cmd_next, "daily": cmd_daily, "queue": cmd_queue, "retry": cmd_retry}[args.cmd]
    sys.exit(handler(args, db) or 0)


if __name__ == "__main__":
    main()

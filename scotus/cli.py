"""scotus_books command line.

  python -m scotus.cli scrape [TERM ...]       update the catalog from supremecourt.gov (default: current + previous term)
  python -m scotus.cli status                  what's in the catalog and what's been done
  python -m scotus.cli review KEY              extract + clean, write the review report (data/review/)
  python -m scotus.cli build KEY               full pipeline for one opinion: PDF -> audio -> video (no upload)
  python -m scotus.cli next [--dry-run]        build and upload whatever should go out next (new > queue.txt > backfill)
  python -m scotus.cli daily                   what the daily timer runs: scrape, then next
  python -m scotus.cli queue add KEY ...       add opinions to queue.txt; also: queue list, queue remove KEY
  python -m scotus.cli retry KEY               clear an opinion's failure count so daily tries it again

KEY is the catalog key "{term}-{R number}", e.g. 25-64; a docket number like 25-112 also works.
"""
import argparse
import fcntl
import json
import sys
import traceback
from datetime import date, datetime

from . import DATA, ROOT, catalog, scrape
from .catalog import now

QUEUE = ROOT / "queue.txt"
MAX_FAILURES = 2        # after this many failed attempts, daily skips an opinion until `retry`
OLDEST_TERM = 18        # supremecourt.gov term pages go back to OT2018
NEW_RELEASE_DAYS = 14   # opinions released this recently jump ahead of the queue


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


def pick_next(db):
    """What to publish next: recent releases first, then queue.txt in order, then backfill (newest first).
    Skips anything already uploaded and anything that has failed MAX_FAILURES times."""
    ok = "uploaded IS NULL AND coalesce(failures, 0) < ?"
    row = db.execute(f"""SELECT * FROM opinions WHERE {ok} AND date >= date('now', ?)
                         ORDER BY date, rnum""", (MAX_FAILURES, f"-{NEW_RELEASE_DAYS} days")).fetchone()
    if row:
        return row, "new release"
    for ref in queue_refs():
        row = db.execute(f"SELECT * FROM opinions WHERE (key = ? OR lower(docket) = lower(?)) AND {ok}",
                         (ref, ref, MAX_FAILURES)).fetchone()
        if row:
            return row, "queue.txt"
    row = db.execute(f"SELECT * FROM opinions WHERE {ok} ORDER BY date DESC, rnum DESC", (MAX_FAILURES,)).fetchone()
    return row, "backfill"


def publish(db, row, privacy, voice="am_michael", model=None):
    """Build (unless already built) and upload one opinion. Records failures instead of raising."""
    from .upload import upload
    out = DATA / "build" / row["key"]
    try:
        if not (row["rendered"] and (out / "video.mp4").exists() and (out / "meta.json").exists()):
            out = build(db, row, voice, model)
        video_id = upload(out, privacy)
    except Exception as e:
        catalog.mark(db, row["key"], failures=(row["failures"] or 0) + 1, last_error=f"{type(e).__name__}: {e}"[:500])
        traceback.print_exc()
        return None
    catalog.mark(db, row["key"], uploaded=now(), youtube_id=video_id, last_error=None)
    return video_id


def cmd_next(args, db):
    row, why = pick_next(db)
    if row is None:
        print("nothing left to publish")
        return 0
    print(f"next: {row['key']} {row['name']} ({row['date']}) [{why}]", flush=True)
    if args.dry_run:
        return 0
    video_id = publish(db, row, args.privacy, args.voice, args.model)
    if video_id is None:
        print(f"FAILED: {row['key']} {row['name']}", file=sys.stderr)
        return 1
    print(f"uploaded {row['key']} ({args.privacy}): https://youtu.be/{video_id}")
    return 0


def cmd_daily(args, db):
    """Scrape for new opinions, then publish one. Holds a lock so overlapping runs can't double-upload."""
    lock = open(DATA / "daily.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another daily run is in progress; exiting")
        return 0
    print(f"=== daily run {datetime.now().isoformat(timespec='seconds')} ===", flush=True)
    args.terms = []
    try:
        cmd_scrape(args, db)
    except Exception:
        traceback.print_exc()   # the site being down shouldn't stop us publishing from the backlog
    # when the backfill runs dry, reach one term further back
    while pick_next(db)[0] is None:
        oldest = db.execute("SELECT min(term) t FROM opinions").fetchone()["t"]
        if oldest is None or oldest <= OLDEST_TERM:
            break
        args.terms = [oldest - 1]
        cmd_scrape(args, db)
    return cmd_next(args, db)


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
            p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"],
                           help="YouTube visibility for uploads (default private; API uploads stay private until "
                                "the project passes Google's audit)")
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

"""scotus_books command line.

  python -m scotus.cli scrape [TERM ...]       update the catalog from supremecourt.gov (default: current + previous term)
  python -m scotus.cli status                  what's in the catalog and what's been done
  python -m scotus.cli review KEY              extract + clean, write the review report (data/review/)
  python -m scotus.cli build KEY [--voice V]   full pipeline for one opinion: PDF -> audio -> video
  python -m scotus.cli next [--dry-run]        build whatever should go out next (new > queue.txt > backfill)
  python -m scotus.cli queue add KEY|DOCKET    add an opinion to queue.txt

KEY is the catalog key "{term}-{R number}", e.g. 25-64; a docket number like 25-112 also works.
"""
import argparse
import json
import sys
from datetime import date, datetime

from . import DATA, ROOT, catalog, scrape
from .catalog import now

QUEUE = ROOT / "queue.txt"


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
    if QUEUE.exists():
        q = [l.strip() for l in QUEUE.read_text().splitlines() if l.strip() and not l.startswith("#")]
        print(f"queue.txt: {len(q)} entries")


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


def pick_next(db):
    """New releases first, then queue.txt in order, then backfill (newest unrendered first)."""
    newest = db.execute("""SELECT * FROM opinions WHERE rendered IS NULL AND date >= date('now', '-14 days')
                           ORDER BY date, rnum""").fetchone()
    if newest:
        return newest, "new release"
    if QUEUE.exists():
        for line in QUEUE.read_text().splitlines():
            ref = line.split("#")[0].strip()
            if not ref:
                continue
            row = db.execute("SELECT * FROM opinions WHERE (key = ? OR lower(docket) = lower(?)) AND rendered IS NULL",
                             (ref, ref)).fetchone()
            if row:
                return row, "queue.txt"
    row = db.execute("SELECT * FROM opinions WHERE rendered IS NULL ORDER BY date DESC, rnum DESC").fetchone()
    return row, "backfill"


def cmd_next(args, db):
    row, why = pick_next(db)
    if row is None:
        print("nothing left to build")
        return
    print(f"next: {row['key']} {row['name']} ({row['date']}) [{why}]")
    if not args.dry_run:
        out = build(db, row, args.voice, args.model)
        print(f"built -> {out}")


def cmd_queue(args, db):
    row = find(db, args.ref)
    with QUEUE.open("a") as f:
        f.write(f"{row['key']}  # {row['name']}\n")
    print(f"queued {row['key']} {row['name']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scotus", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scrape"); p.add_argument("terms", nargs="*")
    sub.add_parser("status")
    p = sub.add_parser("review"); p.add_argument("ref")
    for name in ("build", "next"):
        p = sub.add_parser(name)
        if name == "build":
            p.add_argument("ref")
        else:
            p.add_argument("--dry-run", action="store_true")
        p.add_argument("--voice", default="am_michael")
        p.add_argument("--model", help="default: full model on GPU, int8 on CPU")
    p = sub.add_parser("queue"); p.add_argument("action", choices=["add"]); p.add_argument("ref")
    args = ap.parse_args(argv)
    db = catalog.connect()
    {"scrape": cmd_scrape, "status": cmd_status, "review": cmd_review, "build": cmd_build,
     "next": cmd_next, "queue": cmd_queue}[args.cmd](args, db)


if __name__ == "__main__":
    main()

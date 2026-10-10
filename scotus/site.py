"""The public list of uploaded readings: docs/opinions.html on the GitHub Pages site.

  python -m scotus.site            regenerate docs/opinions.html
  python -m scotus.site --push     regenerate, then commit and push it if it changed (what daily does)
"""
import argparse
import html
import json
import subprocess
import sys
from datetime import datetime, timezone

from . import DATA, ROOT, catalog

PAGE = ROOT / "docs" / "opinions.html"


def video_privacy(video_ids):
    """{video_id: privacyStatus} from YouTube, or {} if the API isn't reachable. 1 quota unit per 50 videos."""
    if not video_ids:
        return {}
    try:
        from googleapiclient.discovery import build
        from .upload import credentials
        yt = build("youtube", "v3", credentials=credentials())
        out = {}
        for i in range(0, len(video_ids), 50):
            resp = yt.videos().list(part="status", id=",".join(video_ids[i:i + 50])).execute()
            out.update({v["id"]: v["status"]["privacyStatus"] for v in resp.get("items", [])})
        return out
    except Exception as e:   # the page is still useful without visibility info
        print(f"couldn't read video visibility from YouTube: {e}", file=sys.stderr)
        return {}


def entries(db):
    rows = db.execute("SELECT * FROM opinions WHERE youtube_id IS NOT NULL ORDER BY date DESC, rnum DESC").fetchall()
    privacy = video_privacy([r["youtube_id"] for r in rows])
    out = []
    for r in rows:
        meta_path = DATA / "build" / r["key"] / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        out.append({
            "key": r["key"], "name": r["name"], "docket": r["docket"], "date": r["date"],
            "term": f"OT20{r['term']:02d}", "citation": r["citation"], "author": meta.get("author", ""),
            "video": f"https://youtu.be/{r['youtube_id']}", "pdf": r["pdf_url"],
            "privacy": privacy.get(r["youtube_id"], "unknown"),
        })
    return out


def _date(iso):
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{d:%b} {d.day}, {d.year}"


def render(items):
    rows = []
    for e in items:
        badge = "" if e["privacy"] == "public" else f' <span class="badge">{html.escape(e["privacy"])}</span>'
        search = " ".join([e["name"], e["docket"], e["term"], e["citation"], e["author"], e["date"]]).lower()
        rows.append(f"""      <tr data-search="{html.escape(search)}">
        <td class="date"><time datetime="{e['date']}">{_date(e['date'])}</time><span class="term">{e['term']}</span></td>
        <td class="case"><span class="name">{html.escape(e['name'])}</span><span class="meta">No. {html.escape(e['docket'])}{' · ' + html.escape(e['author']) if e['author'] else ''}</span></td>
        <td class="links"><a href="{e['video']}">Watch</a>{badge} <a href="{html.escape(e['pdf'])}">Official text</a></td>
      </tr>""")
    updated = datetime.now(timezone.utc).strftime("%B %d, %Y").replace(" 0", " ")
    count = f"{len(items)} reading{'s' if len(items) != 1 else ''}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Opinions Read Aloud</title>
  <meta name="description" content="Every Supreme Court opinion published as an audio reading, with links to the video and the official text.">
  <link rel="stylesheet" href="style.css">
</head>
<body>
<main class="wide">
  <nav><a href="./">Home</a><a href="opinions.html">Opinions</a><a href="privacy.html">Privacy Policy</a><a href="terms.html">Terms of Service</a></nav>

  <p class="kicker">SCOTUS Books</p>
  <h1>Opinions read aloud</h1>
  <p class="muted">{count}, newest decision first. Updated {updated}. Videos marked private aren't viewable yet.</p>

  <input id="filter" type="search" placeholder="Search cases, dockets, terms, Justices" aria-label="Search opinions">

  <table id="opinions">
    <thead><tr><th>Decided</th><th>Case</th><th>Links</th></tr></thead>
    <tbody>
{chr(10).join(rows) if rows else '      <tr><td colspan="3" class="muted">Nothing published yet.</td></tr>'}
    </tbody>
  </table>
  <p id="none" class="muted" hidden>No opinions match that search.</p>

  <footer>SCOTUS Books is not affiliated with or endorsed by the Supreme Court of the United States.</footer>
</main>
<script>
  const input = document.getElementById("filter");
  const rows = [...document.querySelectorAll("#opinions tbody tr[data-search]")];
  input.addEventListener("input", () => {{
    const words = input.value.toLowerCase().split(/\\s+/).filter(Boolean);
    let shown = 0;
    for (const row of rows) {{
      const hit = words.every(w => row.dataset.search.includes(w));
      row.hidden = !hit;
      shown += hit;
    }}
    document.getElementById("none").hidden = shown > 0 || rows.length === 0;
  }});
</script>
</body>
</html>
"""


def write(db=None):
    db = db or catalog.connect()
    PAGE.write_text(render(entries(db)))
    return PAGE


def push():
    """Commit and push docs/opinions.html if it changed. Only that file is committed."""
    rel = str(PAGE.relative_to(ROOT))
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True)
    if not git("status", "--porcelain", "--", rel).stdout.strip():
        print("opinions page unchanged")
        return True
    # only the "Updated <date>" line changed: not worth a commit
    if git("diff", "--quiet", "-I", "Updated [A-Z][a-z]+ [0-9]+, [0-9]{4}", "--", rel).returncode == 0 \
            and git("ls-files", "--error-unmatch", "--", rel).returncode == 0:
        git("checkout", "--", rel)
        print("opinions page unchanged")
        return True
    msg = f"Update opinions list ({datetime.now(timezone.utc):%Y-%m-%d})"
    for step in (["add", "--", rel], ["commit", "-m", msg, "--", rel], ["push", "-q", "origin", "HEAD"]):
        r = git(*step)
        if r.returncode != 0:
            print(f"git {step[0]} failed: {r.stderr.strip()}", file=sys.stderr)
            return False
    print("opinions page pushed")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="commit and push docs/opinions.html if it changed")
    args = ap.parse_args()
    print(f"wrote {write()}")
    if args.push:
        sys.exit(0 if push() else 1)

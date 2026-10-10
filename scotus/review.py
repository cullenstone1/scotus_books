"""Review reports: show exactly what the cleaner removed.

  review.py <pdf> [out_dir]   writes <name>.html (colored) and <name>.review.txt (terminal-friendly)

In the text report, removed text is wrapped in markers:
  [-S ... S-]  whole citation sentence dropped
  [-C ... C-]  citation removed from inside a sentence
  [-G ... G-]  citation removed together with its signal ("see", "cf.")
  [-P ... P-]  parenthetical removed
"""
import html
import sys
from pathlib import Path

from . import DATA
from .clean import clean_doc
from .extract import extract

TEXT_MARK = {"sentence": "S", "cite": "C", "signal": "G", "paren": "P"}
CSS = """
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --sentence:#c62828; --cite:#e65100; --signal:#ad1457; --paren:#6a1b9a; --mark:#fdecea; }
@media (prefers-color-scheme: dark) { :root { --bg:#161617; --fg:#e8e8ea; --muted:#9a9aa0; --sentence:#ff8a80; --cite:#ffb74d; --signal:#f48fb1; --paren:#ce93d8; --mark:#3a1d1d; } }
body { background:var(--bg); color:var(--fg); font:16px/1.6 Georgia, serif; max-width:46rem; margin:2rem auto; padding:0 16px; }
h1 { font:600 1.3rem system-ui, sans-serif; } h2 { font:600 1.05rem system-ui, sans-serif; margin-top:2.5rem; }
h3 { font:600 .95rem system-ui, sans-serif; color:var(--muted); }
.legend, .stats { font:14px system-ui, sans-serif; color:var(--muted); }
del { text-decoration:line-through; background:var(--mark); }
del.sentence { color:var(--sentence); } del.cite { color:var(--cite); } del.signal { color:var(--signal); } del.paren { color:var(--paren); }
details { margin:.5rem 0 1rem; } summary { cursor:pointer; color:var(--muted); font:14px system-ui, sans-serif; }
"""


def render_html(doc, title):
    total = removed = 0
    body = []
    for sec in doc["sections"]:
        body.append(f"<h2>{html.escape(sec['title'])}</h2>")
        for p in sec["paragraphs"]:
            if p["type"] == "heading":
                body.append(f"<h3>{html.escape(p['text'])}</h3>")
                continue
            parts = []
            for seg, tag in p["segments"]:
                total += len(seg)
                if tag:
                    removed += len(seg)
                    parts.append(f'<del class="{tag}" title="{tag}">{html.escape(seg)}</del>')
                else:
                    parts.append(html.escape(seg))
            body.append(f"<p>{''.join(parts)}</p>")
            body.append(f"<details><summary>cleaned</summary><p>{html.escape(p['clean'])}</p></details>")
    pct = 100 * removed / max(total, 1)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Review: {html.escape(title)}</title>
<style>{CSS}</style></head><body>
<h1>{html.escape(title)}</h1>
<p class="stats">{len(doc['sections'])} sections · {pct:.1f}% of characters removed · format: {doc['meta']['format']}</p>
<p class="legend"><del class="sentence">citation sentence</del> · <del class="cite">citation in a sentence</del> ·
<del class="signal">citation with signal</del> · <del class="paren">parenthetical</del></p>
{''.join(body)}
</body></html>"""


def render_text(doc):
    out = []
    for sec in doc["sections"]:
        out.append(f"######## {sec['title']}\n")
        for p in sec["paragraphs"]:
            if p["type"] == "heading":
                out.append(f"## {p['text']}\n")
                continue
            out.append("".join(f"[-{TEXT_MARK[t]} {s} {TEXT_MARK[t]}-]" if t else s for s, t in p["segments"]) + "\n")
    return "\n".join(out)


def review(pdf, out_dir=None):
    out_dir = Path(out_dir or DATA / "review")
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = clean_doc(extract(pdf))
    name = Path(pdf).stem
    (out_dir / f"{name}.html").write_text(render_html(doc, name))
    (out_dir / f"{name}.review.txt").write_text(render_text(doc))
    return doc


if __name__ == "__main__":
    review(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

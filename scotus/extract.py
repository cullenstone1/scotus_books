"""PDF -> structured opinion text.

Handles both formats the Court publishes:
  * slip opinions (Word-made, released on decision day), and
  * preliminary prints (typeset by Miles 33; replace the slip PDF a few months later).

Everything is decided from layout, not regexes over flat text:
  * running headers sit above HEADER_CUT on every page,
  * footnotes sit below a separator (a "——————" text line in slip opinions,
    a short drawn rule in preliminary prints),
  * footnote markers are small raised digits,
  * notices, watermarks and cover pages use font sizes body text never uses.
"""
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field, asdict

import pymupdf
from wordfreq import zipf_frequency

HEADER_CUT = 150      # pt from top; running headers live above this in both formats
MIN_BODY_SIZE = 8.5   # notices, "(Slip Opinion)", cover-page fine print are smaller
WATERMARK_SIZE = 18   # "Page Proof Pending Publication" is ~21.7pt
SUPERSCRIPT_RATIO = 0.75
MARKER = ""     # placed after an "f" glyph wide enough to be an fi/fl ligature

SUPERSCRIPT_RE = re.compile(r"^[\d*†‡§]+$")
FOOTNOTE_RULE_RE = re.compile(r"^—{4,}$")   # caption rules are "____" and centered; footnote rules are "——" at the margin
DOCKET_RE = re.compile(r"^Nos?\.\s.*\b(Argued|Decided|Submitted)\b")
TITLE_RE = re.compile(
    r"^((chief\s+)?justice\s+[\w’'.-]+.*\b(delivered|announced|concurring|dissenting|respecting)\b.*"
    r"|statement\s+of\s+(the\s+)?(chief\s+)?justice\b.*"
    r"|per\s+curiam)\.\s*\*?$",
    re.IGNORECASE | re.DOTALL,
)
COUNSEL_RE = re.compile(r"\b(argued the cause|filed a brief|briefs? of amici|were filed for)\b", re.IGNORECASE)
FIGURE_RE = re.compile(r"^(Figure|Fig\.|Table|Chart|Map)\s+\d+[A-Z]?[.:]\s")   # captions of maps, charts
HEADING_RE = re.compile(r"^(([IVXL]+|[A-Za-z]|\d+)([–-]([IVXL]+|[A-Z]|\d+))*|\*(\s*\*)*|APPENDIX.*|Appendix.*)$")


@dataclass
class Line:
    page: int
    x0: float
    x1: float
    y0: float
    size: float
    text: str


@dataclass
class Section:
    kind: str          # syllabus | majority | plurality | concurrence | dissent | statement | per_curiam | other
    title: str
    paragraphs: list = field(default_factory=list)   # [{"type": "para"|"heading", "text": str}]


# ---------------------------------------------------------------- page level

def _span_text(span):
    """Text of a rawdict span, flagging over-wide 'f' glyphs (lost fi/fl ligatures)."""
    out = []
    for ch in span["chars"]:
        c = ch["c"]
        out.append(c)
        if c == "f":
            w = ch["bbox"][2] - ch["bbox"][0]
            if w > 0.45 * span["size"]:
                out.append(MARKER)
    return unicodedata.normalize("NFKC", "".join(out)) if any(ord(c) > 0xFB00 for c in out) else "".join(out)


def _footnote_cut(page, lines):
    """y coordinate where the footnote area starts on this page, or None."""
    h = page.rect.height
    for d in page.get_drawings():
        r = d["rect"]
        if r.height < 2 and 20 < r.width < 150 and r.y0 > h * 0.25 and r.x0 < page.rect.width * 0.35:
            return r.y0 - 1
    for ln in lines:
        if FOOTNOTE_RULE_RE.match(ln["text"].strip()) and ln["y0"] > h * 0.25 and ln["x0"] < page.rect.width * 0.35:
            return ln["y0"] - 1
    return None


def page_lines(page, pno):
    """Body lines of a page, top to bottom, with markers for section starts."""
    raw = []
    for block in page.get_text("rawdict")["blocks"]:
        for ln in block.get("lines", []):
            spans = [s for s in ln["spans"] if s["chars"]]
            if not spans:
                continue
            for s in spans:
                s["text"] = _span_text(s)
            text = "".join(s["text"] for s in spans)
            if not text.strip():
                continue
            main = max(spans, key=lambda s: len(s["chars"]))
            raw.append({"spans": spans, "text": text, "y0": ln["bbox"][1], "x0": ln["bbox"][0], "size": main["size"]})

    cut = _footnote_cut(page, raw)
    body_sizes = [r["size"] for r in raw if r["size"] >= MIN_BODY_SIZE and r["size"] < WATERMARK_SIZE]
    page_size = max(set(body_sizes), key=body_sizes.count) if body_sizes else 11

    out = []
    for r in raw:
        if r["y0"] < HEADER_CUT or (cut is not None and r["y0"] >= cut):
            continue
        if r["size"] >= WATERMARK_SIZE or re.fullmatch(r"\s*\d+\s*", r["text"]):   # watermark, page number
            continue
        if r["size"] > 14 and "SUPREME COURT" in r["text"]:
            out.append(Line(pno, 0, 0, r["y0"], r["size"], "<<SECTION>>"))
            continue
        kept = [s for s in r["spans"]
                if not (s["size"] < SUPERSCRIPT_RATIO * max(r["size"], page_size)
                        and SUPERSCRIPT_RE.match(s["text"].strip() or "x"))]
        if not kept or not "".join(s["text"] for s in kept).strip():
            continue
        if r["size"] < MIN_BODY_SIZE:
            continue
        x0 = min(c["bbox"][0] for s in kept for c in s["chars"] if c["c"].strip())
        x1 = max(c["bbox"][2] for s in kept for c in s["chars"] if c["c"].strip())
        out.append(Line(pno, x0, x1, r["y0"], r["size"], "".join(s["text"] for s in kept)))

    # PyMuPDF sometimes splits one visual line (e.g. around a dropped superscript); merge by y.
    out.sort(key=lambda l: (round(l.y0 / 3), l.x0))
    merged = []
    for ln in out:
        if merged and abs(merged[-1].y0 - ln.y0) < 3 and ln.text != "<<SECTION>>" and merged[-1].text != "<<SECTION>>":
            m = merged[-1]
            m.text = m.text.rstrip() + " " + ln.text.lstrip()
            m.x1 = max(m.x1, ln.x1)
        else:
            merged.append(ln)
    return merged


# ---------------------------------------------------------- paragraph level

def _join(a, b):
    """Join two consecutive lines, undoing end-of-line hyphenation.

    Both formats use "-" and soft hyphens for real and for line-break hyphens alike,
    so decide with a dictionary: "gerrymander-ing" joins, "track-and" keeps its hyphen.
    """
    a = a.rstrip()
    b = b.lstrip()
    if a.endswith(("—", "–")):
        return a + b
    if a.endswith(("-", "\u00ad")) and not a.endswith("--"):
        left = re.search(r"([A-Za-z\ue000]+)[-\u00ad]$", a)
        right = re.match(r"([A-Za-z\ue000]+)", b)
        if left and right:
            l, r = (w.replace(MARKER, "i").lower() for w in (left.group(1), right.group(1)))
            halves = min(zipf_frequency(l, "en"), zipf_frequency(r, "en"))
            if halves < 2.5 or zipf_frequency(l + r, "en") >= 2.5:
                return a[:-1] + b
        return a[:-1] + "-" + b
    return a + " " + b


def _fix_ligatures(text):
    def repl(m):
        word = m.group(0)
        n = word.count(MARKER)
        best, score = word.replace(MARKER, ""), -1.0
        for choice in ("i", "l", ""):
            cand = word.replace(MARKER, choice, n)
            s = zipf_frequency(cand.lower(), "en")
            if choice == "i":
                s += 0.01   # "fi" is the commoner ligature; break ties toward it
            if s > score:
                best, score = cand, s
        return best
    return re.sub(r"[A-Za-z’']*[A-Za-z’']*", repl, text)


def _clean_text(t):
    t = _fix_ligatures(t)
    t = t.replace("\u00ad", "")
    t = re.sub(r"(?<=[.,;:”’)])[*†‡]+", "", t)   # same-size footnote markers
    t = t.replace("`", "‘")             # prelim prints use ` for an opening single quote
    t = re.sub(r"[ \t ]+", " ", t)
    return t.strip()


def paragraphs(lines):
    """Group body lines into paragraphs. Yields ("section"|"para"|"heading", text, line)."""
    body = [l for l in lines if l.text != "<<SECTION>>"]
    if not body:
        return
    # Typical left margin and right edge per page, from the most common line starts/ends.
    # Syllabus (9pt) and opinion (11pt) text can share a page with different margins,
    # so measure margins per page and text size.
    margins, rights = {}, {}
    for p, size in {(l.page, round(l.size)) for l in body}:
        same = [l for l in body if l.page == p and round(l.size) == size]
        xs = [round(l.x0) for l in same]
        x1s = sorted(round(l.x1) for l in same)
        margins[p, size] = max(set(xs), key=xs.count)
        rights[p, size] = x1s[int(len(x1s) * 0.9)]

    cur, cur_first = None, None
    prev = None
    for ln in lines:
        if ln.text == "<<SECTION>>":
            if cur:
                yield "para", _clean_text(cur), cur_first
            cur, prev = None, None
            yield "section", "", ln
            continue
        text = ln.text
        margin, right = margins[ln.page, round(ln.size)], rights[ln.page, round(ln.size)]
        centered = abs((ln.x0 + ln.x1) / 2 - (margin + right) / 2) < 15 and ln.x0 > margin + 20
        if centered and HEADING_RE.match(text.strip()):
            if cur:
                yield "para", _clean_text(cur), cur_first
            cur, prev = None, None
            yield "heading", text.strip(), ln
            continue
        if cur is None or prev is None:
            new_para = True
        elif prev.page == ln.page:
            first_outdented = prev is cur_first and prev.x0 < margin - 3      # "Held:" hanging indent
            new_para = (
                (ln.x0 > prev.x0 + 6 and not first_outdented)                  # first-line indent, block quote start
                or (ln.x0 < prev.x0 - 6 and prev is not cur_first)            # back out of a block quote
                or prev.x1 < right - 25                                        # previous line ended short
                or ln.y0 - prev.y0 > 2.2 * ln.size                             # vertical gap
                or abs(ln.size - prev.size) > 1                                # caption lines, syllabus -> opinion
                or ((prev.x0 > margin + 50 or ln.x0 > margin + 50)            # right-set lines: "It is so ordered."
                    and re.search(r"[.?!:][”’)]?$", prev.text.rstrip()))
                or (abs(ln.x0 - prev.x0) <= 2 and 8 <= ln.x0 - margin <= 14    # two indented first lines in a row
                    and re.search(r"[.?!][”’)]?$", prev.text.rstrip()))
            )
        else:
            new_para = ln.x0 > margin + 6                                      # indented at the top of a new page
        # a right-set line finishing an unfinished sentence ("... Circuits are   Affirmed.") continues it
        if (prev is not None and ln.x0 > margin + 50 and ln.x1 >= right - 5 and abs(ln.size - prev.size) <= 1
                and not re.search(r"[.?!:][”’)]?$", prev.text.rstrip())):
            new_para = False
        # a line ending in a hyphen never ends a paragraph
        if cur is not None and prev is not None and re.search(r"[A-Za-z][-\u00ad]$", cur.rstrip()) and ln.size == prev.size:
            new_para = False
        if new_para and cur is not None:
            yield "para", _clean_text(cur), cur_first
            cur = None
        if cur is None:
            cur, cur_first = text, ln
        else:
            cur = _join(cur, text)
        prev = ln
    if cur:
        yield "para", _clean_text(cur), cur_first


def _kind(title):
    t = title.lower()
    if t.startswith("per curiam"):
        return "per_curiam"
    if t.startswith("statement"):
        return "statement"
    if "dissenting" in t:
        return "dissent"
    if "concurring" in t:
        return "concurrence"
    if "announced the judgment" in t:
        return "plurality"
    if "delivered the opinion" in t:
        return "majority"
    return "other"


# ------------------------------------------------------------ document level

def extract(pdf_path):
    doc = pymupdf.open(pdf_path)
    meta = {"source": str(pdf_path), "creator": doc.metadata.get("creator", ""), "pages": len(doc)}
    meta["format"] = "preliminary_print" if "Miles 33" in meta["creator"] else "slip"

    lines = []
    for pno, page in enumerate(doc):
        if pno == 0 and "PRELIMINARY PRINT" in page.get_text()[:500]:
            continue
        lines.extend(page_lines(page, pno))

    sections, cur = [], None
    state = "front"       # front | caption | section | counsel | appendix
    pending_title = None  # title paragraphs can wrap across what looks like two paragraphs
    for kind, text, ln in paragraphs(lines):
        if kind == "section":
            state = "caption"
            continue
        if pending_title is not None:
            joined = _join(pending_title, text)
            if TITLE_RE.match(joined) and len(joined) < 500:
                cur = Section(_kind(joined), _clean_text(joined))
                sections.append(cur)
                state, pending_title = "section", None
                continue
            pending_title = None
        if kind == "para" and len(text) < 500 and TITLE_RE.match(text):
            cur = Section(_kind(text), text)
            sections.append(cur)
            state = "section"
            continue
        if kind == "para" and re.match(r"^(chief\s+)?justice\s+\S+.*,$|^(chief\s+)?justice\s+\S+.*\b(and|with whom)$",
                                       text, re.IGNORECASE) and len(text) < 300 and state != "section":
            pending_title = text
            continue
        if kind == "para" and DOCKET_RE.match(text) and not any(s.kind == "syllabus" for s in sections):
            cur = Section("syllabus", "Syllabus")
            sections.append(cur)
            state = "section"
            continue
        if state == "section" and cur and cur.kind == "syllabus" and COUNSEL_RE.search(text):
            state = "counsel"
            continue
        if (kind == "heading" and text.lower().startswith("appendix")) or (kind == "para" and text.startswith("Reporter’s Note")):
            state = "appendix"
            continue
        if kind == "para" and FIGURE_RE.match(text):
            continue
        if kind == "para" and len(text) <= 8 and HEADING_RE.match(text):   # off-center headings: "B", "*"
            kind = "heading"
        if state == "section" and cur is not None:
            cur.paragraphs.append({"type": kind, "text": text})
    return {"meta": meta, "sections": [asdict(s) for s in sections]}


def to_text(doc):
    out = []
    for s in doc["sections"]:
        out.append(f"######## [{s['kind']}] {s['title']}\n")
        for p in s["paragraphs"]:
            out.append(("## " if p["type"] == "heading" else "") + p["text"] + "\n")
    return "\n".join(out)


if __name__ == "__main__":
    d = extract(sys.argv[1])
    if len(sys.argv) > 2 and sys.argv[2] == "--json":
        print(json.dumps(d, indent=1, ensure_ascii=False))
    else:
        print(to_text(d))

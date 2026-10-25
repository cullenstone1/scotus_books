"""Section detection on real opinions. PDFs live in data/ (not in git); missing ones are skipped.
Fetch them with: python -m scotus.cli review <key>"""
import re
from pathlib import Path

import pytest

from scotus import DATA
from scotus.extract import extract

EXPECTED = {
    "pdf/24/604us1r01_2dq3.pdf": ["syllabus", "per_curiam"],
    "pdf/25/26a388_q86b.pdf": ["per_curiam"],
    "pdf/23/602us1r30_g3bi.pdf": ["syllabus", "majority", "dissent"],
    "pdf/25/609us1r60_7mip.pdf": ["syllabus", "plurality", "concurrence", "dissent"],
    "pdf/25/609us2r64_7mio.pdf": ["syllabus", "majority", "concurrence", "concurrence", "dissent", "dissent"],
    "pdf/25/609us2r65_g314.pdf": ["syllabus", "majority", "dissent"],   # opinion starts on a mostly-footnote page
    "pdf/25/609us1r53_i4dk.pdf": ["syllabus", "majority", "dissent"],   # dissent title wraps onto a second line
    "pdf/25/24-43_2b35.pdf": ["syllabus", "majority", "concurrence", "concurrence", "dissent", "dissent"],
    "pdf/22-807_3e04.pdf": ["syllabus", "majority", "concurrence", "dissent"],
}


@pytest.mark.parametrize("path,kinds", EXPECTED.items())
def test_sections(path, kinds):
    pdf = DATA / path
    if not pdf.exists():
        pytest.skip(f"{pdf} not downloaded")
    doc = extract(pdf)
    assert [s["kind"] for s in doc["sections"]] == kinds
    for s in doc["sections"]:
        assert s["paragraphs"], f"empty section {s['title']}"
        assert "join" not in s["title"].lower() or re.search(r"with whom|in which", s["title"], re.I), f"title lost its first line: {s['title']}"
        assert not any(re.match(r"^(chief\s+)?justice\s+\S+.*\b(and|with whom)$", p["text"], re.I) for p in s["paragraphs"]), \
            "the first line of a wrapped title was left in the text"
        last = [p for p in s["paragraphs"] if p["type"] == "para"][-1]["text"]
        assert not last.endswith(("-", "­")), f"section ends mid-word: {last[-60:]}"

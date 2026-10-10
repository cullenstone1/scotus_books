"""Scrape supremecourt.gov slip-opinion term pages into the catalog and download PDFs."""
import hashlib
import json
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import DATA, catalog

BASE = "https://www.supremecourt.gov"
TERM_URL = BASE + "/opinions/slipopinion/{term:02d}"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) scotus_books (personal audiobook project)"}
DELAY = 2.0  # seconds between requests; be polite

_session = requests.Session()
_session.headers.update(HEADERS)
_last = 0.0


def get(url):
    global _last
    wait = DELAY - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    r = _session.get(url, timeout=60)
    _last = time.monotonic()
    r.raise_for_status()
    return r


def parse_term(html, term):
    """Yield one dict per opinion row on a term page."""
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 6:
            continue
        rnum, date, docket, name_td, author, citation = tds
        links = name_td.find_all("a")
        if not links:
            continue
        if not date.get_text(strip=True):   # placeholder rows on a term page with no opinions yet
            continue
        main = links[0]
        revisions = [urljoin(BASE, a["href"]) for a in links[1:]]
        rnum = rnum.get_text(strip=True)
        yield {
            "key": f"{term:02d}-{rnum}",
            "term": term,
            "rnum": rnum,
            "date": datetime.strptime(date.get_text(strip=True), "%m/%d/%y").date().isoformat(),
            "docket": docket.get_text(strip=True),
            "name": main.get_text(strip=True),
            "author": author.get_text(strip=True),
            "citation": citation.get_text(strip=True),
            "summary": main.get("title", "").strip(),
            "pdf_url": urljoin(BASE, main["href"]),
            "revisions": json.dumps(revisions),
        }


def scrape_term(db, term):
    html = get(TERM_URL.format(term=term)).text
    counts = {"new": 0, "changed": 0, None: 0}
    for row in parse_term(html, term):
        counts[catalog.upsert(db, row)] += 1
    db.commit()
    return counts["new"], counts["changed"]


def download(db, row):
    """Download the row's PDF if missing or its url changed. Returns the local path."""
    name = row["pdf_url"].rsplit("/", 1)[-1]
    path = DATA / "pdf" / f"{row['term']:02d}" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        data = get(row["pdf_url"]).content
        if not data.startswith(b"%PDF"):
            raise ValueError(f"not a PDF: {row['pdf_url']}")
        path.write_bytes(data)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    catalog.mark(db, row["key"], pdf_path=str(path.relative_to(DATA)), pdf_sha256=sha)
    return path

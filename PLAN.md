# scotus_books: review and plan

*Written 2026-10-10.*

The most important things up front:

- **The old regexes had a real bug.** In `parseTextFile.py:30` the `re.DOTALL` lands in `re.sub`'s `count` slot. That made every regex remove at most 16 matches, which explains part of why stuff kept getting left behind.
- **Someone already does a podcast version.** Nothing equivalent turned up on YouTube, and the Court doesn't publish anything like this.
- **NVIDIA's voice tools need a CUDA GPU.** Without one, the plan uses a CPU-friendly open voice instead; see [Voice](#voice-ttspy).

## 1. What exists today

Work stopped mid-way through the cleaning step: pdfminer extraction, about 50 regexes in `constants.py`, and a check-by-hand loop.

**The good part:** `parsePdf.py` was already using layout (the horizontal rule above footnotes) and font sizes to find footnotes. That's the right idea, and font size alone turns out to be enough. On a page of the sample slip opinion (`collection/22-807_3e04.pdf`), poppler reports word heights of:

- 16.6 for body text
- 13.6 for footnotes and running headers
- 10.5 / 9.0 for superscript footnote numbers

Footnotes and the markers can be dropped by size, and the headers ("Cite as…", page numbers) by their position at the top of the page. No regexes needed for that part.

**Bugs and cruft:**

- **The `re.sub` bug above.** Each regex removes at most 16 matches.
- **Duplicate keys in `expressions`.** `justice_dissenting` and `parenthetical_year_with_stuff` each appear twice, and the later one silently overwrites the earlier.
- **Some patterns delete real text.** `\(.*?\d{4}\)`, `§.*?[. ]` and `[1-9*] \n` match more than citations, and `leftover_dots` strips punctuation. The leftovers show in the output: `"(ADA),."` and `"50 F. 4th 259."`.
- **`separateOpinions()` would crash.** It assigns module globals without `global`, so it raises on `numConcurrences += 1`. It's also never called.
- **`regex_tester.py` is broken.** It imports `citationRegexes`, which is commented out.
- **Leftover files:** `pdfminer_venv_source_me` points at a path that no longer exists, and `output.txt` is a 4.4MB debug dump that's committed to the repo.

**PDF format:** neither is LaTeX now. There are two formats:

- **Slip opinions** (what comes out on decision day) are made from Word with Acrobat PDFMaker.
- **Preliminary prints** (the `601us1r01` file) are typeset with Miles 33.

Months later, the Court replaces the slip opinion link with the preliminary print (visible on the current term page), so the code has to recognize both. The PDF's `Creator` metadata tells them apart.

## 2. Is someone already doing this?

- **The Court doesn't.** It doesn't even livestream opinion announcements; that audio only appears at the start of the next term.
- **Oyez** has the announcement audio, and recently started pairing it with AI avatar videos. Those are the justices' short spoken summaries, not the written opinions.
- **"Supreme Court Opinions" podcast** (Apple, Spotify, TuneIn) is very close to this idea: full opinions "in their entirety, but with citations omitted," with episodes through July 2026. Unknown whether it uses TTS, whether it includes dissents, or whether it's on YouTube. Listen to an episode before committing.
- **"Supreme Court Decision Syllabus"** reads only the syllabus.

No YouTube channel doing full opinions turned up. The openings are YouTube itself, the full back catalogue, and chapters for each opinion. The idea isn't new, though.

## 3. Plan

```
scotus/
  catalog.py   SQLite: one row per opinion, with status for each stage
  scrape.py    term pages → catalog
  extract.py   PDF → structured doc (syllabus / majority / concurrences / dissents)
  clean.py     citation removal + making text speakable
  review.py    HTML report: removed text in red, changed text in yellow
  tts.py       Kokoro (or a GPU model), with a cache per sentence
  render.py    ffmpeg → m4a + mp4 + chapter timestamps
  upload.py    YouTube Data API
  cli.py       scotus daily | queue add 22-807 | backfill | review <id>
data/          (gitignored) pdf/ text/ audio/ video/
tests/golden/  ~10 opinions with checked expected output
```

### Scraper (`scrape.py`)

- Read `supremecourt.gov/opinions/slipopinion/{term}`. The table has date, docket, name, author, citation and the PDF link.
- Also read the "Relating to Orders" pages.
- Check a few times on weekdays. Opinions come out around 10am ET, so a timer at about 10:15, 12:00 and 16:00 is plenty. Keep requests slow and use a normal user-agent.
- Store the URL and a sha256 of each PDF. That way revisions (the `_diff_` PDFs) and slip opinions being swapped for preliminary prints get noticed.

### Extraction and cleaning (`extract.py`, `clean.py`), the hard part

Each step replaces something that used to be done by hand:

1. **Use PyMuPDF instead of pdfminer.** It gives font size and position for every piece of text, so footnotes, superscript markers and headers are dropped by layout, as shown above.
2. **Split the document** at "JUSTICE X delivered the opinion…", "…concurring", "…dissenting". These become YouTube chapters.
3. **Use eyecite for citations instead of hand-written regexes.** It's Free Law Project's open-source citation finder, used on millions of court documents. It finds full, short, *Id.*, *supra* and statute citations and returns where each one sits in the text.
4. **Remove whole citation sentences.** In legal writing, a sentence starting with *See*, *Cf.*, *E.g.*, *But see* or *Compare* that is mostly citations goes entirely. Inside normal sentences, keep the case name ("*Brown* held…") and remove just the reporter citation and parenthetical.
5. **Make the text speakable:**
   - § → "section"
   - "v." → "versus"
   - "Part III–C" → "Part three C"
   - "[t]he" → "the"
   - ". . ." → a pause
   - "J." / "JJ." → Justice / Justices
6. **Replace "read the output, write another regex" with two things:**
   - `review.py`, an HTML diff report for scanning the removals in a minute or two.
   - Golden tests, so a fix for one opinion can't break another.

### Voice (`tts.py`)

- **The NVIDIA tool was almost certainly NeMo or Riva.** Both need a CUDA GPU.
- **Kokoro-82M is the recommended default** (Apache-licensed, CPU-friendly). Comparisons generally rate it above Piper.
- **Piper is the fallback.** It's much faster on CPU but sounds more robotic.
- **First task: time the candidates on the machine that will render, using a real opinion.**
- **Cache audio for each sentence,** keyed on its text. Fixing one sentence then only re-renders that sentence.
- **Keep a pronunciation list** for terms like certiorari, amicus curiae, Sotomayor and Kavanaugh.
- **Mixing:** join the clips with ffmpeg, then normalize loudness.

### Video (`render.py`)

- A still title card (case name, docket, date, author) plus the audio, made with `ffmpeg -loop 1 -tune stillimage`. Files stay small and render fast.
- Chapter timestamps go in the description, along with a link to the official PDF and the "footnotes and citations omitted" notice from `generateHeader.py`.

### Upload (`upload.py`)

- Use the YouTube Data API v3 with a one-time OAuth login and a saved refresh token. The default quota allows about 6 uploads a day, which is plenty.
- **Start this early. Videos uploaded from an unaudited API project are locked to private** until Google approves the project, and approval can take weeks. Apply while building everything else.
- **Policy:**
  - Mark the videos as synthetic/altered content where YouTube asks.
  - Mass-produced TTS channels often can't earn ad money under YouTube's rules on repetitive content, so don't plan on monetization.
  - The opinions themselves are public domain, so copyright isn't an issue.

### Daily scheduler and back catalogue (`cli.py daily`)

- One upload a day, chosen in this order:
  1. New opinions not yet done
  2. The queue file (`queue.txt` of dockets or citations)
  3. Backfill, walking back through terms
- The term pages go back to OT2018. Before that, there are the bound-volume PDFs on supremecourt.gov or CourtListener's API (free token). CourtListener has older opinion text with citations already marked up, which may beat parsing old PDFs. Worth checking when we get there.
- The SQLite catalog tracks what's done, so the backfill never repeats anything.

### Build order

1. Environment setup and moving the old experiments into `archive/`.
2. Extraction and cleaning with golden tests.
3. Voice comparison on the rendering machine.
4. Rendering.
5. Scraper and catalog.
6. Upload (submit the audit request during step 2).
7. Daily timer and backfill.

## Setup

System packages:

```
sudo apt install python3-venv python3-pip ffmpeg espeak-ng
```

`espeak-ng` is used by both Kokoro and Piper for pronunciation. Python packages (PyMuPDF, eyecite, kokoro-onnx, google-api-python-client) go in a project venv. GPU rendering also needs an NVIDIA driver.

## Open questions

- **Should the syllabus be included?** It's written by the Reporter of Decisions, not the Court. It could be a short intro chapter or skipped.
- **One video per case,** with chapters for majority, concurrences and dissents, or separate videos for each?
- **Keep the old pdfminer/regex code,** or move it to `archive/` and start fresh on PyMuPDF and eyecite?

## Sources

- [Supreme Court Opinions podcast (TuneIn)](https://tunein.com/podcasts/News/Supreme-Court-Opinions-p2105701/)
- [Supreme Court Decision Syllabus podcast](https://pocketcasts.com/podcast/supreme-court-decision-syllabus-scotus-podcast/265ba660-f6f8-0135-c25e-7d73a919276a)
- [NPR/WYSO: Oyez AI avatar project](https://www.wyso.org/npr-news/2026-02-11/an-ai-project-is-creating-videos-to-go-with-supreme-court-justices-real-words)
- [WFAE: press corps asks Court to livestream opinions](https://www.wfae.org/united-states-world/2025-06-11/supreme-court-press-corps-asks-chief-justice-to-live-stream-courts-opinions)
- [supremecourt.gov OT2025 slip opinions](https://www.supremecourt.gov/opinions/slipopinion/25)
- [eyecite (GitHub)](https://github.com/freelawproject/eyecite/)
- [Kokoro vs Piper benchmark](https://offlinetts.com/blog/browser-tts-showdown-kokoro-piper-kitten/)
- [CodeSOTA: Piper vs Kokoro](https://www.codesota.com/text-to-speech/piper-vs-kokoro)

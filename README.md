# SCOTUS Books

Supreme Court opinions, read aloud and published to YouTube, one a day.

The program watches supremecourt.gov for new opinions and pulls the text out of the official PDF. It drops the footnotes and legal citations, reads what's left with an open-source voice (Kokoro), and makes a video with a chapter and a title card for each opinion: the syllabus, the opinion of the Court, and each concurrence and dissent. Then it uploads the video to the **SupremeDork** YouTube channel. When there's nothing new, it works through a list you choose and then back through past terms.

Website (privacy policy and terms for Google): https://cullenstone1.github.io/scotus_books/

---

## How it works

```
supremecourt.gov term pages ──scrape──▶ catalog (data/catalog.db)
                                             │  pick next: new release > queue.txt > backfill
                                             ▼
official PDF ──extract──▶ sections & paragraphs ──clean──▶ citations removed
                                                               │
                         ┌─────────────────────────────────────┘
                         ▼
                  speak (text for the voice) ──tts──▶ audio + chapter times
                                                          │
                              title cards ──render──▶ video.mp4 ──upload──▶ YouTube
```

| Step | Module | What it does |
|---|---|---|
| Scrape | `scotus/scrape.py`, `scotus/catalog.py` | Reads the term pages (`/opinions/slipopinion/25` etc.) into a SQLite catalog, one row per opinion, and downloads PDFs. |
| Extract | `scotus/extract.py` | Uses page layout to drop running headers, footnotes (everything below the footnote rule), footnote markers (small raised digits) and watermarks. It also splits the opinion into syllabus / majority / concurrences / dissents, rejoins hyphenated words and repairs lost "fi"/"fl" letters. It handles both PDF formats the Court publishes: Word-made **slip opinions** on decision day, and typeset **preliminary prints** that replace them a few months later. |
| Clean | `scotus/clean.py` | Removes citations. It uses [eyecite](https://github.com/freelawproject/eyecite) for case and statute citations, plus patterns for record cites, "Id.", "supra", the Constitution and treatises. A sentence that is only citations is dropped whole. In other sentences, case names used as part of the sentence are kept ("In *Carpenter v. United States*, the Court held…"). |
| Review | `scotus/review.py` | Writes a report showing every cut, so you can check the cleaning (see [Reviewing the text](#reviewing-the-text)). |
| Speak | `scotus/speak.py` | Rewrites text for the voice: "Kagan, J." → "Justice Kagan", "Title IX" → "Title Nine", "367–374" → "367 to 374", acronyms spelled out letter by letter. |
| TTS | `scotus/tts.py` | Kokoro text-to-speech, cached per sentence, with pauses between sentences, paragraphs and sections, and pronunciation overrides. |
| Render | `scotus/render.py` | Title card, plus a card for each section showing the writing Justice's name and official portrait; the video switches cards at each chapter. |
| Upload | `scotus/upload.py` | YouTube Data API upload with title, description, chapters and custom thumbnail. |
| CLI | `scotus/cli.py` | Ties it together; `daily` is what the timer runs. |

---

## Daily operation

A systemd timer runs `python -m scotus.cli daily` every day at **11:00 New York time**, an hour after the Court releases opinions. Each run:

1. Scrapes the current and previous term for new or changed opinions.
2. Picks **one** opinion to publish (see the next section).
3. Builds it (a few minutes on a GPU) and uploads it.

If the box was off at 11:00, the run happens as soon as it's back on.

**Uploads are private** until Google approves the API audit (see [YouTube API audit](#youtube-api-audit)). After approval, switch to public as described in [Daily timer](#daily-timer).

Check on it:

```bash
cd ~/scotus_books
.venv/bin/python -m scotus.cli status      # counts per term, the queue, failures, and what's next
tail -50 data/logs/daily.log               # what the last runs did
systemctl --user list-timers scotus-daily  # when it runs next
```

Run it right now instead of waiting:

```bash
systemctl --user start scotus-daily        # same as the 11:00 run, logged to data/logs/daily.log
```

### What gets published next

Every run publishes the first match from this list, skipping anything already uploaded:

1. **New releases:** opinions released in the last 14 days, oldest first. If the Court releases three in one day, they go out on three consecutive days.
2. **Your queue:** `queue.txt`, top to bottom.
3. **Backfill:** everything else in the catalog, newest first. When the catalog runs out, `daily` scrapes one term further back on its own, down to OT2018, the oldest term page on supremecourt.gov.

### The queue

`queue.txt` (in the repo folder, not tracked by git) is your list of opinions to publish ahead of the backfill. Manage it with the CLI, or edit the file by hand: one catalog key or docket number per line, with `#` starting a comment.

```bash
.venv/bin/python -m scotus.cli queue add 25-64            # by catalog key
.venv/bin/python -m scotus.cli queue add 24-43 25-112     # several at once; docket numbers work too
.venv/bin/python -m scotus.cli queue list                 # what's queued and whether it's uploaded yet
.venv/bin/python -m scotus.cli queue remove 25-64
```

Entries stay in the file after they're uploaded and are simply skipped, so the file doubles as a record of what you picked. A queued opinion has to be in the catalog. For older terms, `scrape` the term first, e.g. `scrape 21`.

**Catalog keys** look like `25-64`: the October Term (OT2025), then the opinion's number on that term's page (the "R-" column on supremecourt.gov). `status` and `queue list` show them; you can also look them up with `sqlite3 data/catalog.db "select key, name from opinions where name like '%Chatrie%'"`.

### When something fails

If a build or upload fails, the run exits with an error in the log, and that opinion's failure count goes up. The next day it's tried again. After **two** failures it's skipped, so one bad PDF can't block the channel, and `status` lists it with the error. Once fixed:

```bash
.venv/bin/python -m scotus.cli retry 25-64   # clear the failure count; the next run tries it again
```

If the build succeeded but the upload failed (quota, network), the next attempt re-uploads the existing video without rebuilding.

---

## Commands

All commands run from `~/scotus_books` as `.venv/bin/python -m scotus.cli <command>`.

| Command | What it does |
|---|---|
| `scrape [TERM ...]` | Update the catalog from supremecourt.gov. Default: current and previous term. `scrape 22 21` scrapes specific terms. |
| `status` | Opinions per term, how many are extracted / rendered / uploaded, the queue, failures, and what's next. |
| `review KEY` | Extract and clean one opinion and write its review report to `data/review/`. Nothing is rendered. |
| `build KEY` | Full build of one opinion into `data/build/KEY/` (`video.mp4`, `reading.m4a`, cards, `chapters.txt`, `meta.json`). No upload. |
| `next [--dry-run] [--privacy P]` | Publish the next opinion (build + upload). `--dry-run` only says what it would pick. |
| `daily [--privacy P]` | What the timer runs: scrape, then `next`. Holds a lock so two runs can't overlap. |
| `queue add/list/remove` | Manage `queue.txt` (see [The queue](#the-queue)). |
| `retry KEY` | Clear an opinion's failure count. |

Other entry points:

```bash
.venv/bin/python -m scotus.upload KEY --privacy private   # upload an already-built opinion
.venv/bin/python -m scotus.upload --auth                  # one-time YouTube sign-in (see Setup)
.venv/bin/python -m scotus.tts PDF --limit 10             # render the first few items of any PDF, for quick voice tests
.venv/bin/python -m scotus.review PDF                     # review report for any PDF
.venv/bin/python -m pytest -q tests                       # regression tests
```

`--voice` on `build` and `next` picks a Kokoro voice (default `am_michael`). Kokoro has about a dozen English voices (`am_*`, `af_*`, `bm_*`, `bf_*`).

---

## Reviewing the text

The cleaner catches most citations, but legal writing has a long tail, especially strings of historical sources in older-style opinions. To check an opinion:

```bash
.venv/bin/python -m scotus.cli review 25-64
less data/review/609us2r64_7mio.review.txt
```

In the `.review.txt` report, everything removed is wrapped in markers:

- `[-S … S-]` a whole sentence dropped because it was only citations
- `[-C … C-]` a citation removed from inside a sentence
- `[-G … G-]` a citation removed along with its signal word ("See", "Cf.")
- `[-P … P-]` a citation parenthetical removed ("(internal quotation marks omitted)")

The `.html` version shows the same thing in color. Copy it to your own computer with `scp <host>:scotus_books/data/review/NAME.html .` and open it in a browser.

**When you find a mistake**, either something left in or something wrongly cut:

1. Add the paragraph and the output it *should* produce to `CASES` in `tests/test_clean.py`.
2. Fix `scotus/clean.py` until `pytest -q tests` passes.

The tests keep earlier fixes from breaking. `tests/test_extract.py` similarly checks that each test PDF splits into the right sections. The PDFs it needs live in `data/pdf/`; missing ones are skipped.

### Pronunciation

If the voice says a word wrong, add it to `LEXICON` in `scotus/tts.py` with the phonemes to use, for example:

```python
LEXICON = {
    "syllabus": "sˈɪləbəs",
    "certiorari": "sˌɜːʃioʊɹˈɑːɹi",
}
```

To see what the voice currently does with a word:

```bash
.venv/bin/python -c "from scotus.tts import Synth; print(Synth().phonemes('certiorari'))"
```

Acronyms are spelled out letter by letter unless they're in `SAID_AS_WORDS` in `scotus/speak.py` (NATO, NASA, NAACP…). Add to that list any acronym that's said as a word.

Audio is cached per sentence in `data/tts_cache/`. After a pronunciation fix, rebuilding re-voices only the sentences that changed.

---

## Setup

These are the steps to set it up from scratch on Ubuntu with an NVIDIA GPU.

### 1. System packages and code

```bash
sudo apt install -y git python3-venv python3-pip ffmpeg espeak-ng fonts-noto-core
git clone git@github.com:cullenstone1/scotus_books.git ~/scotus_books
cd ~/scotus_books
git config user.name "Cullen Stone"
git config user.email cullen_stone@yahoo.com
```

### 2. Python environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# GPU: replace the CPU runtime with the CUDA one (pip brings its own CUDA/cuDNN libraries)
.venv/bin/pip uninstall -y onnxruntime
.venv/bin/pip install "onnxruntime-gpu[cuda,cudnn]"
```

On a machine without an NVIDIA GPU, skip the last two lines. It runs on CPU, using the smaller int8 model; on a modest CPU expect about real time or slower, so a 2-hour opinion can take hours.

### 3. Voice models

```bash
mkdir -p models && cd models
for f in kokoro-v1.0.onnx kokoro-v1.0.int8.onnx voices-v1.0.bin; do
  wget -q https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f
done
cd ..
```

### 4. Check it works

```bash
.venv/bin/python -m pytest -q tests
.venv/bin/python -m scotus.cli scrape
.venv/bin/python -m scotus.cli build 24-1        # Hamm v. Smith, about 5 minutes of audio
```

### 5. YouTube credentials

Google Cloud project with **YouTube Data API v3** enabled. Its OAuth consent screen is set to *In production*, and the privacy policy, terms and home page URLs come from the [website](https://cullenstone1.github.io/scotus_books/). The OAuth client is of type *Desktop app*.

1. Put the client's JSON at `~/.config/scotus_books/client_secret.json`.
2. The sign-in redirects to `localhost:8765` on the box, so open a tunnel from the computer whose browser you'll use:
   ```bash
   ssh -L 8765:localhost:8765 <host>
   ```
3. In that SSH session:
   ```bash
   cd ~/scotus_books && .venv/bin/python -m scotus.upload --auth
   ```
4. Open the printed URL in that computer's browser. Pick the **SupremeDork** channel, not "Cullen Stone". Click through "Google hasn't verified this app" (Advanced → Go to …) and allow both permissions.
5. Lock down the folder: `chmod 700 ~/.config/scotus_books && chmod 600 ~/.config/scotus_books/*`

The token is saved as `~/.config/scotus_books/token.json` and refreshes itself.

### 6. Daily timer

```bash
mkdir -p ~/.config/systemd/user data/logs
cp deploy/scotus-daily.service deploy/scotus-daily.timer ~/.config/systemd/user/
loginctl enable-linger "$USER"                  # run timers even when you're not logged in
systemctl --user daemon-reload
systemctl --user enable --now scotus-daily.timer
systemctl --user list-timers scotus-daily
```

**To switch uploads to public** after the audit, edit `--privacy private` to `--privacy public` in `~/.config/systemd/user/scotus-daily.service` (and in `deploy/` to keep the repo in step), then run `systemctl --user daemon-reload`. Videos already uploaded as private stay private; change those in YouTube Studio.

**To pause** daily uploads: `systemctl --user stop scotus-daily.timer`. To resume: `systemctl --user start scotus-daily.timer`.

---

## YouTube API audit

Videos uploaded through the API by a project Google hasn't audited are **locked to private**. To lift that, submit Google's *YouTube API Services – Audit and Quota Extension* form, with:

- the website, privacy policy and terms URLs
- the SupremeDork channel
- a description of the app: it uploads audio readings of Supreme Court opinions to its owner's own channel, about one video a day, and accesses no other users' data

The default quota (10,000 units a day) is plenty: an upload costs 1,600 units and a thumbnail 50.

The channel also needs to stay **verified** (youtube.com/verify, done for SupremeDork). Verification is what allows videos over 15 minutes and custom thumbnails.

---

## Troubleshooting

**Renders are slow, or the log says `CPUExecutionProvider`.** The GPU isn't being used. Check:

```bash
.venv/bin/python -c "from scotus.tts import Synth; print(Synth().kokoro.sess.get_providers())"
```

It should list `CUDAExecutionProvider` first. If not, make sure `onnxruntime-gpu[cuda,cudnn]` is installed and plain `onnxruntime` isn't (`pip list | grep onnx`), and that `nvidia-smi` works.

**`not authorized; run: python -m scotus.upload --auth`.** The YouTube token is missing or was revoked (e.g. from myaccount.google.com/permissions). Redo [step 5](#5-youtube-credentials).

**`quotaExceeded`.** The daily API quota ran out; it resets at midnight Pacific time. The opinion counts one failure and is retried, without rebuilding, on the next run.

**An opinion fails twice and gets skipped.** `status` shows the error. Look at it with `review KEY`, fix it, then `retry KEY`.

**A paragraph is cut off, or a word is split ("mur… der").** That's an extraction problem (`scotus/extract.py`), usually unusual page layout. Check the extracted text with `.venv/bin/python -m scotus.extract PATH.pdf`. Add the PDF to `EXPECTED` in `tests/test_extract.py` once it's fixed.

---

## Project layout

```
scotus/            the pipeline (see "How it works")
tests/             regression tests for cleaning, speech text and section detection
assets/justices/   public-domain official portraits; sources.tsv lists where each came from
deploy/            systemd service and timer for the daily run
docs/              the project website (GitHub Pages): home, privacy policy, terms
archive/           the original 2024 pdfminer + regex experiments
PLAN.md            the original plan and research notes
queue.txt          your publish queue (not in git)
data/              not in git:
  catalog.db         the catalog
  pdf/               downloaded opinions
  review/            review reports
  build/KEY/         finished builds: video.mp4, reading.m4a, cards, chapters, meta.json
  tts_cache/         per-sentence audio cache
  logs/daily.log     timer output
models/            Kokoro model files (not in git)
~/.config/scotus_books/   YouTube client secret and token (never in git)
```

All opinion text is the work of the U.S. government and in the public domain. This project is not affiliated with the Supreme Court of the United States.

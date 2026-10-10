"""Render a cleaned opinion to audio with Kokoro, plus chapter timestamps.

Audio is synthesized one chunk (a sentence or a few short ones) at a time and cached
by (model, voice, speed, text), so fixing one sentence only re-renders that sentence.

  python -m scotus.tts <pdf> [--voice am_michael] [--model kokoro-v1.0.int8.onnx]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from . import DATA, MODELS
from .clean import clean_doc, split_sentences
from .extract import extract
from .speak import heading, speakable

SAMPLE_RATE = 24000
PAUSE = {"sentence": 0.15, "paragraph": 0.6, "heading": 0.8, "section": 2.0}
MAX_CHUNK = 350   # characters; Kokoro handles ~500 phonemes per pass, and shorter chunks cache better

INTRO = ("This is an audio reading of the opinion of the Supreme Court of the United States in {name}, "
         "decided {date}. Footnotes and citations have been omitted for listening. "
         "The full text, with citations, is linked in the description.")
SYLLABUS_NOTE = ("The syllabus is prepared by the Reporter of Decisions for the convenience of the reader "
                 "and is not part of the opinion of the Court.")
SECTION_NAMES = {
    "syllabus": "Syllabus",
    "majority": "Opinion of the Court",
    "plurality": "Opinion announcing the judgment",
    "per_curiam": "Per Curiam",
}


class Synth:
    def __init__(self, model="kokoro-v1.0.int8.onnx", voice="am_michael", speed=1.0, cache=None):
        import onnxruntime as ort
        from kokoro_onnx import Kokoro

        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
        so = ort.SessionOptions()
        so.intra_op_num_threads = os.cpu_count() or 4
        sess = ort.InferenceSession(str(MODELS / model), so, providers=providers)
        self.kokoro = Kokoro.from_session(sess, str(MODELS / "voices-v1.0.bin"))
        self.model, self.voice, self.speed = model, voice, speed
        self.cache = Path(cache or DATA / "tts_cache")
        self.cache.mkdir(parents=True, exist_ok=True)
        self.synth_seconds = 0.0

    def say(self, text):
        key = hashlib.sha1(f"{self.model}|{self.voice}|{self.speed}|{text}".encode()).hexdigest()
        path = self.cache / f"{key}.npy"
        if path.exists():
            return np.load(path)
        t0 = time.time()
        samples, sr = self.kokoro.create(text, voice=self.voice, speed=self.speed, lang="en-us")
        self.synth_seconds += time.time() - t0
        assert sr == SAMPLE_RATE
        samples = _trim(samples.astype(np.float32))
        np.save(path, samples)
        return samples


def _trim(x, threshold=0.01):
    """Drop leading/trailing near-silence so our own pauses control the pacing."""
    idx = np.flatnonzero(np.abs(x) > threshold)
    if len(idx) == 0:
        return x[:0]
    pad = int(0.03 * SAMPLE_RATE)
    return x[max(0, idx[0] - pad): idx[-1] + pad]


def chunks(text):
    """Sentences, with short neighbors merged, each at most MAX_CHUNK characters where possible."""
    out = []
    for a, b in split_sentences(text):
        s = text[a:b].strip()
        if not s:
            continue
        if out and len(out[-1]) + len(s) < 120:
            out[-1] += " " + s
        elif len(s) > MAX_CHUNK:
            # split long sentences at semicolons, then commas
            parts = re.split(r"(?<=;)\s+", s)
            for p in parts:
                while len(p) > MAX_CHUNK:
                    cut = p.rfind(", ", 0, MAX_CHUNK)
                    cut = cut + 1 if cut > 80 else MAX_CHUNK
                    out.append(p[:cut].strip())
                    p = p[cut:].strip()
                if p:
                    out.append(p)
        else:
            out.append(s)
    return out


def section_title(sec):
    if sec["kind"] in SECTION_NAMES and sec["kind"] != "majority":
        return SECTION_NAMES[sec["kind"]]
    return speakable(sec["title"]).rstrip(".")


def script(doc, name, date):
    """The full reading as a list of (kind, text) items, kind in chapter|heading|para."""
    items = [("chapter", "Introduction"), ("para", INTRO.format(name=speakable(name), date=date))]
    for sec in doc["sections"]:
        items.append(("chapter", section_title(sec)))
        if sec["kind"] == "syllabus":
            items.append(("heading", "Syllabus."))
            items.append(("para", SYLLABUS_NOTE))
        else:
            items.append(("heading", speakable(sec["title"])))
        for p in sec["paragraphs"]:
            if p["type"] == "heading":
                h = heading(p["text"])
                if h:
                    items.append(("heading", h + "."))
            elif p["clean"]:
                items.append(("para", speakable(p["clean"])))
    return items


def render(items, synth, out_wav, log=print):
    """Synthesize the script into one WAV. Returns chapters [(title, start_seconds)]."""
    silence = {k: np.zeros(int(v * SAMPLE_RATE), dtype=np.float32) for k, v in PAUSE.items()}
    pieces, chapters, t = [], [], 0.0
    total = sum(len(x) for k, x in items if k != "chapter")
    done, started = 0, time.time()
    for kind, text in items:
        if kind == "chapter":
            if pieces:
                pieces.append(silence["section"])
                t += PAUSE["section"]
            chapters.append((text, t))
            continue
        for i, c in enumerate(chunks(text)):
            audio = synth.say(c)
            pieces.append(audio)
            t += len(audio) / SAMPLE_RATE
            pieces.append(silence["sentence"])
            t += PAUSE["sentence"]
        pause = silence["heading"] if kind == "heading" else silence["paragraph"]
        pieces.append(pause)
        t += len(pause) / SAMPLE_RATE
        done += len(text)
        elapsed = time.time() - started
        log(f"\r{100 * done / total:5.1f}%  audio {t / 60:6.1f} min  elapsed {elapsed / 60:6.1f} min", end="")
    log("")
    audio = np.concatenate(pieces)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_wav, audio, SAMPLE_RATE, subtype="PCM_16")
    return chapters


def encode(wav, out_m4a):
    """Loudness-normalize to podcast level and encode AAC."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100",
                    "-c:a", "aac", "-b:a", "96k", str(out_m4a)], check=True)


def chapters_text(chapters):
    """YouTube-style chapter list: first must be 0:00."""
    def ts(s):
        s = int(s)
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    return "\n".join(f"{ts(t)} {title}" for title, t in chapters)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--name", help="case name (default: from catalog or filename)")
    ap.add_argument("--date", default="")
    ap.add_argument("--voice", default="am_michael")
    ap.add_argument("--model", default="kokoro-v1.0.int8.onnx")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--out", help="output directory (default data/audio/<pdf name>)")
    ap.add_argument("--limit", type=int, help="only the first N script items (for quick tests)")
    args = ap.parse_args(argv)

    pdf = Path(args.pdf)
    out = Path(args.out or DATA / "audio" / pdf.stem)
    doc = clean_doc(extract(pdf))
    items = script(doc, args.name or pdf.stem, args.date)
    if args.limit:
        items = items[:args.limit]
    out.mkdir(parents=True, exist_ok=True)
    (out / "script.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))

    synth = Synth(args.model, args.voice, args.speed)
    t0 = time.time()
    chapters = render(items, synth, out / "reading.wav", log=lambda *a, **k: print(*a, **k, file=sys.stderr, flush=True))
    encode(out / "reading.wav", out / "reading.m4a")
    (out / "chapters.txt").write_text(chapters_text(chapters) + "\n")
    dur = sf.info(out / "reading.wav").duration
    print(f"{dur / 60:.1f} min of audio in {(time.time() - t0) / 60:.1f} min "
          f"(synthesis {synth.synth_seconds / 60:.1f} min) -> {out}")


if __name__ == "__main__":
    main()

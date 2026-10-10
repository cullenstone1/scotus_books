"""Title card + still-image video for an opinion reading."""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import ROOT

FONTS = Path("/usr/share/fonts/truetype/noto")
PORTRAITS = ROOT / "assets" / "justices"
KIND_LABELS = {
    "syllabus": "Syllabus",
    "majority": "Opinion of the Court",
    "plurality": "Opinion announcing the judgment",
    "per_curiam": "Per Curiam",
    "concurrence": "Concurring",
    "dissent": "Dissenting",
    "statement": "Statement",
}
W, H = 1920, 1080
BG, FG, MUTED, ACCENT = "#10182b", "#f3efe6", "#a9b0c0", "#c8a24a"


def _font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def _wrap(text, font, width):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if font.getlength(trial) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur] if cur else lines


def title_card(out_png, name, subtitle_lines, footer="Audio reading · footnotes and citations omitted"):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x = 160
    d.text((x, 170), "SUPREME COURT OF THE UNITED STATES", font=_font("NotoSans-Bold.ttf", 34), fill=ACCENT)
    d.line((x, 235, x + 220, 235), fill=ACCENT, width=4)

    # case name: shrink until it fits in at most 3 lines
    for size in (104, 92, 80, 70, 60):
        f = _font("NotoSerif-Bold.ttf", size)
        lines = _wrap(name, f, W - 2 * x)
        if len(lines) <= 3:
            break
    y = 290
    for line in lines:
        d.text((x, y), line, font=f, fill=FG)
        y += int(size * 1.22)

    y += 40
    sub = _font("NotoSerif-Regular.ttf", 44)
    for line in subtitle_lines:
        d.text((x, y), line, font=sub, fill=MUTED)
        y += 64

    d.text((x, H - 130), footer, font=_font("NotoSans-Regular.ttf", 32), fill=MUTED)
    img.save(out_png)
    return out_png


def justices():
    """surname -> full name, for Justices we have portraits of."""
    rows = (PORTRAITS / "sources.tsv").read_text().splitlines()[1:]
    return {r.split("\t")[0]: r.split("\t")[1] for r in rows if r.strip()}


def section_author(title):
    """Surname of the Justice who wrote a section, from its title, or None."""
    import re
    m = re.match(r"\s*(?:chief\s+)?justice\s+([A-Za-z’'-]+)", title, re.IGNORECASE)
    return m.group(1).lower().replace("’", "'") if m else None


def justice_title(title):
    """"Chief Justice" or "Justice", from how the section heading itself names its author.
    The Court styles the sitting Chief as "CHIEF JUSTICE X", so this follows whoever holds the office,
    and an earlier opinion by a later Chief (written as an Associate Justice) correctly stays "Justice"."""
    import re
    return "Chief Justice" if re.match(r"\s*chief\s+justice\b", title, re.IGNORECASE) else "Justice"


def kind_label(kind, title):
    t = title.lower()
    if "concurring" in t and "dissenting" in t:
        return "Concurring in part and dissenting in part"
    if "concurring in the judgment" in t:
        return "Concurring in the judgment"
    return KIND_LABELS.get(kind, "Opinion")


def section_card(out_png, case_name, kind, title, spoken_title=None):
    """Card shown while one section is read: label, Justice name and portrait when we have one."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x = 160
    author = section_author(title)
    names = justices()
    portrait = PORTRAITS / f"{author}.jpg" if author else None
    has_portrait = portrait is not None and portrait.exists()
    text_w = (1100 if has_portrait else W - 2 * x) - x

    d.text((x, 170), kind_label(kind, title).upper(), font=_font("NotoSans-Bold.ttf", 34), fill=ACCENT)
    d.line((x, 235, x + 220, 235), fill=ACCENT, width=4)
    y = 290
    if author:
        name = names.get(author, author.title())
        prefix = justice_title(title)
        for size in (96, 84, 72, 62):
            f = _font("NotoSerif-Bold.ttf", size)
            lines = _wrap(f"{prefix} {name}", f, text_w)
            if len(lines) <= 2:
                break
        for line in lines:
            d.text((x, y), line, font=f, fill=FG)
            y += int(size * 1.2)
        y += 30
        if spoken_title and ("with whom" in spoken_title or "joins" in spoken_title or "join," in spoken_title):
            small = _font("NotoSerif-Italic.ttf", 36)
            for line in _wrap(spoken_title, small, text_w)[:3]:
                d.text((x, y), line, font=small, fill=MUTED)
                y += 50
            y += 30
    sub = _font("NotoSerif-Regular.ttf", 44)
    for line in _wrap(case_name, sub, text_w)[:3]:
        d.text((x, y), line, font=sub, fill=MUTED)
        y += 62

    if has_portrait:
        im = Image.open(portrait).convert("RGB")
        ph = 760
        pw = int(im.width * ph / im.height)
        im = im.resize((pw, ph), Image.LANCZOS)
        px, py = W - 160 - pw, (H - ph) // 2
        d.rectangle((px - 6, py - 6, px + pw + 5, py + ph + 5), outline=ACCENT, width=3)
        img.paste(im, (px, py))
    d.text((x, H - 130), "Audio reading · footnotes and citations omitted", font=_font("NotoSans-Regular.ttf", 32), fill=MUTED)
    img.save(out_png)
    return out_png


def slideshow(cards, audio, out_mp4):
    """Video from [(png, start_seconds)] cards plus the audio; each card shows until the next starts."""
    import soundfile as sf
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  str(audio)], capture_output=True, text=True, check=True).stdout)
    listing = Path(out_mp4).with_suffix(".cards.txt")
    lines = []
    for i, (png, start) in enumerate(cards):
        end = cards[i + 1][1] if i + 1 < len(cards) else total
        lines += [f"file '{Path(png).resolve()}'", f"duration {max(end - start, 1):.3f}"]
    lines.append(f"file '{Path(cards[-1][0]).resolve()}'")   # concat demuxer needs the last file repeated
    listing.write_text("\n".join(lines) + "\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-i", str(audio), "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", "-r", "1", "-c:a", "copy", "-shortest", "-movflags", "+faststart",
                    str(out_mp4)], check=True)
    listing.unlink()
    return out_mp4


def video(card_png, audio, out_mp4):
    """Still image + audio. 1 fps keeps encoding fast and the file small; YouTube accepts it."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "1", "-i", str(card_png),
                    "-i", str(audio), "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", "-r", "1", "-c:a", "copy", "-shortest", "-movflags", "+faststart",
                    str(out_mp4)], check=True)
    return out_mp4

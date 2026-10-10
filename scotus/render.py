"""Title card + still-image video for an opinion reading."""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path("/usr/share/fonts/truetype/noto")
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


def video(card_png, audio, out_mp4):
    """Still image + audio. 1 fps keeps encoding fast and the file small; YouTube accepts it."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "1", "-i", str(card_png),
                    "-i", str(audio), "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", "-r", "1", "-c:a", "copy", "-shortest", "-movflags", "+faststart",
                    str(out_mp4)], check=True)
    return out_mp4

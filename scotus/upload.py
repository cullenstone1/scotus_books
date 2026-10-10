"""Upload a built opinion video to YouTube (Data API v3).

One-time setup (see README "YouTube setup"):
  1. Google Cloud project with "YouTube Data API v3" enabled.
  2. OAuth client of type "Desktop app"; download its JSON to ~/.config/scotus_books/client_secret.json.
  3. python -m scotus.upload --auth     (prints a URL; open it on any machine, see README for the SSH tunnel)

Until Google audits the API project, every video uploaded through the API is locked to private.
"""
import argparse
import json
import sys
from pathlib import Path

from . import DATA, catalog
from .cli import pretty_date
from .catalog import now

CONFIG = Path.home() / ".config" / "scotus_books"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
AUTH_PORT = 8765
CATEGORY_EDUCATION = "27"


def credentials(interactive=False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token = CONFIG / "token.json"
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not interactive:
            sys.exit("not authorized; run: python -m scotus.upload --auth")
        flow = InstalledAppFlow.from_client_secrets_file(str(CONFIG / "client_secret.json"), SCOPES)
        creds = flow.run_local_server(port=AUTH_PORT, open_browser=False,
                                      authorization_prompt_message="Open this URL in a browser:\n{url}\n")
    CONFIG.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json())
    return creds


def title_for(meta):
    year = meta["date"][:4]
    title = f"{meta['name']} ({year}) | Supreme Court Opinion, Read Aloud"
    if len(title) > 100:
        title = f"{meta['name'][:100 - len(f' ({year})') - 1]}… ({year})"
    return title.replace("<", "").replace(">", "")


def description_for(meta):
    parts = [
        f"The Supreme Court's opinion in {meta['name']}, No. {meta['docket']}, decided {pretty_date(meta['date'])}.",
        meta["author"],
        "",
        meta["summary"],
        "",
        "Chapters",
        meta["chapters"],
        "",
        f"Official text (with footnotes and citations): {meta['pdf_url']}",
        "",
        "This reading omits footnotes and legal citations so it can be followed by ear. It is read by a "
        "synthetic voice (Kokoro text-to-speech) and has no commentary. Not affiliated with the Supreme Court.",
    ]
    text = "\n".join(p for p in parts if p is not None)
    return text.replace("<", "‹").replace(">", "›")[:5000]


def upload(build_dir, privacy="private"):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    build_dir = Path(build_dir)
    meta = json.loads((build_dir / "meta.json").read_text())
    youtube = build("youtube", "v3", credentials=credentials())
    body = {
        "snippet": {
            "title": title_for(meta),
            "description": description_for(meta),
            "tags": ["Supreme Court", "SCOTUS", "court opinion", "audiobook", meta["name"]],
            "categoryId": CATEGORY_EDUCATION,
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    media = MediaFileUpload(str(build_dir / "video.mp4"), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"\rupload {100 * status.progress():5.1f}%", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    video_id = resp["id"]
    try:
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(build_dir / "card.png"))).execute()
    except Exception as e:   # custom thumbnails need a verified channel
        print(f"thumbnail not set: {e}", file=sys.stderr)
    return video_id


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("key", nargs="?", help="catalog key of a built opinion (data/build/KEY)")
    ap.add_argument("--auth", action="store_true", help="run the one-time OAuth login")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    args = ap.parse_args(argv)
    if args.auth:
        credentials(interactive=True)
        print(f"saved {CONFIG / 'token.json'}")
        return
    if not args.key:
        ap.error("key required")
    db = catalog.connect()
    video_id = upload(DATA / "build" / args.key, args.privacy)
    catalog.mark(db, args.key, uploaded=now(), youtube_id=video_id)
    print(f"https://youtu.be/{video_id}")


if __name__ == "__main__":
    main()

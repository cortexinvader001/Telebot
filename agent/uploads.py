"""Turn Telegram uploads into text the agent can work with (saves the file, runs Gemini where useful)."""
import re
import time
import uuid
from pathlib import Path

from agent import vision
from agent.workspace import chat_dir, rel, share
from settings import MAX_UPLOAD_BYTES
from tg import get_bot

MEDIA_TYPES = ["photo", "document", "voice", "audio", "video", "video_note"]


def _safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).strip("._") or "file"
    return name[:80]


def _describe(message):
    """-> (kind, file_id, file_size, filename, mime)"""
    ct = message.content_type
    if ct == "photo":
        p = message.photo[-1]  # largest size
        return "photo", p.file_id, p.file_size, f"photo_{int(time.time())}_{uuid.uuid4().hex[:4]}.jpg", "image/jpeg"
    obj = getattr(message, ct)
    default = {"voice": "voice.ogg", "video_note": "video_note.mp4", "video": "video.mp4", "audio": "audio.mp3"}.get(ct, "file")
    name = getattr(obj, "file_name", None) or default
    return ct, obj.file_id, getattr(obj, "file_size", None), name, getattr(obj, "mime_type", None)


def ingest(message) -> str | None:
    """Download the media on `message` and return a text block describing it (None if no media)."""
    if message.content_type not in MEDIA_TYPES:
        return None
    kind, file_id, size, name, mime = _describe(message)
    if size and size > MAX_UPLOAD_BYTES:
        return f"[User sent a {kind} ({size // 1024 // 1024} MB) but Telegram bots can only download files up to 20 MB, so it could not be read. Tell the user.]"

    bot = get_bot()
    try:
        data = bot.download_file(bot.get_file(file_id).file_path)
    except Exception as e:
        return f"[User sent a {kind} but downloading it failed: {e}]"

    dest = chat_dir() / "uploads" / f"{int(time.time())}_{_safe_name(name)}"
    dest.write_bytes(data)
    share(dest)
    mime = mime or vision.guess_mime(dest)
    info = f"[User uploaded {kind}: {rel(dest)} ({mime}, {len(data) // 1024} KB)]"
    caption = (message.caption or "").strip()

    if mime.startswith("image/"):
        try:
            analysis = vision.analyze(dest, caption or None)
        except Exception as e:
            analysis = f"(automatic Gemini analysis failed: {e}; try analyze_file later)"
        info += f"\n[Gemini image analysis{' for the caption question' if caption else ''}]\n{analysis}"
    elif kind in ("voice", "audio", "video_note") or mime.startswith("audio/"):
        try:
            transcript = vision.analyze(dest)
            info += f"\n[Transcript]\n{transcript}"
        except Exception as e:
            info += f"\n(automatic transcription failed: {e})"
    elif mime == "application/pdf":
        info += "\n(PDF: load the 'pdf' skill; use read_file for text or analyze_file for scanned/visual PDFs.)"
    elif kind == "video":
        info += "\n(Video saved. Use shell with ffmpeg to extract frames/audio, then analyze_file on those.)"
    else:
        info += "\n(Use read_file / shell to inspect it.)"

    if caption and not mime.startswith("image/"):
        info += f"\nCaption: {caption}"
    return info

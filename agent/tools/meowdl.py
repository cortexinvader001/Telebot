"""Download YouTube audio/video via MeowDL API."""
import subprocess
import json
import os
import requests
from urllib.parse import quote
from .base import schema

SCHEMA = schema(
    "meowdl_download",
    "[custom] Download audio or video from YouTube using MeowDL API. Accepts song query or direct YouTube URL. Returns local file path, metadata. Audio m4a auto-converts to mp3.",
    {
        "query": {"type": "string", "description": "Song name or search query (e.g. 'Skott Overcome')"},
        "url":   {"type": "string", "description": "Direct YouTube URL to download (optional if query given)"},
        "type":  {"type": "string", "enum": ["audio", "video"], "description": "'audio' or 'video'"},
        "quality": {"type": "string", "description": "Video resolution (360p, 480p, 720p, 1080p). Default 480p."},
        "filename": {"type": "string", "description": "Optional output filename without extension"},
    },
    [],
)


def run(args: dict) -> dict:
    """Download audio or video from YouTube using MeowDL API."""
    query = args.get("query", "").strip()
    yt_url = args.get("url", "").strip()
    content_type = args.get("type", "audio").lower()
    quality = args.get("quality", "480p")
    filename = args.get("filename")

    workspace_root = os.path.join(os.getcwd(), "..", "..", "..", "..", "workspace")
    upload_dir = os.path.join(workspace_root, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    if not yt_url:
        if not query:
            return {"success": False, "error": "Provide either 'query' or 'url'"}
        safe_q = quote(query)
        r = json.loads(requests.get(f"{API_BASE}/search?q={safe_q}&num=5").text)
        if not r.get("success"):
            return {"success": False, "error": f"Search failed: {r}"}
        results = r.get("results", [])
        if not results:
            return {"success": False, "error": "No results found"}
        yt_url = f"https://www.youtube.com/watch?v={results[0]['videoId']}"

    if not yt_url.startswith("http"):
        yt_url = f"https://www.youtube.com/watch?v={yt_url}"

    fmt = "m4a" if content_type == "audio" else "mp4"
    r = json.loads(requests.get(f"{API_BASE}/yt?url={quote(yt_url)}&format={fmt}").text)

    if r.get("status") != "ok":
        return {"success": False, "error": f"Download API error: {json.dumps(r)}"}

    dl_url = r.get("downloadLink") or r.get("download_link") or r.get("link")
    if not dl_url:
        return {"success": False, "error": "No download URL in response"}

    ext = "m4a" if content_type == "audio" else "mp4"
    base_name = filename or (r.get("title") or "media").replace("/", "_")
    out_path = os.path.join(upload_dir, f"{base_name}.{ext}")

    resp = requests.get(dl_url, stream=True, timeout=120)
    if resp.status_code != 200:
        return {"success": False, "error": f"HTTP {resp.status_code} downloading"}

    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)

    size = os.path.getsize(out_path)

    final_path = out_path
    if content_type == "audio" and ext == "m4a" and os.path.exists(out_path):
        mp3_path = out_path.replace(".m4a", ".mp3")
        try:
            subprocess.run(
                ["ffmpeg", "-i", out_path, "-codec:a", "libmp3lame",
                 "-qscale:a", "2", mp3_path, "-y"],
                capture_output=True, timeout=60
            )
            if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                os.remove(out_path)
                final_path = mp3_path
                ext = "mp3"
        except subprocess.TimeoutExpired:
            pass

    return {
        "success": True,
        "filepath": final_path,
        "filename": os.path.basename(final_path),
        "title": r.get("title", ""),
        "channel": r.get("channel", ""),
        "duration": r.get("duration", ""),
        "size_bytes": size,
        "format": ext,
    }


TOOLS = {"meowdl_download": (SCHEMA, run)}

API_BASE = "https://meow-dl.onrender.com"

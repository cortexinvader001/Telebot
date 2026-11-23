"""Which command-line tools can the agent's shell actually use? (bundled bin/ + system PATH)"""
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from agent import sandbox
from settings import ROOT

WANTED = ["python3", "pip", "node", "npm", "git", "curl", "ffmpeg", "ffprobe",
          "pdftotext", "qpdf", "tesseract", "convert", "jq", "zip", "unzip"]
HINTS = {  # how to get what we can't install portably
    "git": "Replit: add `git` to nix packages in .replit",
    "curl": "Replit: add `curl` to nix packages in .replit",
    "ffprobe": "ships with the real ffmpeg package (nix `ffmpeg`)",
    "pdftotext": "Replit nix: `poppler_utils`", "qpdf": "Replit nix: `qpdf`",
    "tesseract": "Replit nix: `tesseract`", "convert": "Replit nix: `imagemagick`",
    "jq": "Replit nix: `jq`", "zip": "Replit nix: `zip`", "unzip": "Replit nix: `unzip`",
    "node": "Replit: enable the nodejs module", "npm": "Replit: enable the nodejs module",
}
_cache = {"t": 0.0, "v": {}}


def status(max_age: int = 60) -> dict:
    """tool -> absolute path or None (cached briefly; bundled bin/ counts)."""
    if time.time() - _cache["t"] > max_age:
        path = sandbox.tool_path()
        _cache.update(t=time.time(), v={t: shutil.which(t, path=path) for t in WANTED})
    return _cache["v"]


def summary() -> tuple[list[str], list[str]]:
    s = status()
    return [t for t, p in s.items() if p], [t for t, p in s.items() if not p]


def ensure(auto_install: bool = True) -> dict:
    """Make sure the essentials exist. Portable fix only for ffmpeg (pip wheel with a bundled static binary,
    linked into bin/). Everything else is reported with a hint. Never raises."""
    _cache["t"] = 0.0
    if auto_install and not status().get("ffmpeg"):
        try:
            for extra in ([], ["--user"]):
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "imageio-ffmpeg", *extra],
                                   capture_output=True, text=True, timeout=600)
                if r.returncode == 0:
                    break
            import imageio_ffmpeg

            exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
            link = ROOT / "bin" / ("ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg")
            link.unlink(missing_ok=True)
            try:
                os.symlink(exe, link)
            except OSError:
                shutil.copy2(exe, link)
            _cache["t"] = 0.0
        except Exception as e:
            print(f"[tools] could not install bundled ffmpeg: {e}")
    return status(0)


def report() -> str:
    have, missing = summary()
    lines = ["[tools] available: " + (", ".join(have) or "none")]
    for t in missing:
        lines.append(f"[tools] missing: {t}" + (f"  ->  {HINTS[t]}" if t in HINTS else ""))
    return "\n".join(lines)

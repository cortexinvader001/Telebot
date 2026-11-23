"""Gemini understanding of images, PDFs, audio and video, tuned for low quotas.

* model chain: cheapest/preferred first; 429 / 404 / 5xx on one model -> try the next (separate quota each)
* key pool: several keys rotate (only useful if they belong to different Google projects)
* cache: the same file + question is never sent twice
"""
import hashlib
import mimetypes
import threading
import time
from collections import OrderedDict
from pathlib import Path

from agent.keypool import KeyPool
from settings import GEMINI_API_KEYS, GEMINI_VISION_MODELS, MAX_UPLOAD_BYTES

SUPPORTED_PREFIXES = ("image/", "audio/", "video/")
SUPPORTED_EXACT = {"application/pdf"}
DEFAULT_PROMPTS = {
    "image": "Describe this image in detail. Transcribe any visible text exactly. Mention anything notable (people count, objects, charts, UI, errors).",
    "audio": "Transcribe this audio verbatim. If it is not speech, describe what you hear.",
    "application": "Summarise this document: structure, key facts, tables and figures.",
    "video": "Describe what happens in this video and transcribe any speech.",
}
COOLDOWN_429 = 65          # per-minute limits reset within a minute
COOLDOWN_DAILY = 3600      # "per day" quota errors: stop hammering that model for an hour
COOLDOWN_MISSING = 3600    # 404: model retired / not available to this project
MAX_WAIT = 20

_pool: KeyPool | None = None
_clients: dict = {}
_model_cool: dict[tuple[int, str], float] = {}   # (key index, model) -> monotonic time usable again
_lock = threading.Lock()
_cache: "OrderedDict[str, str]" = OrderedDict()
CACHE_SIZE = 200


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime is None and path.suffix.lower() in (".oga", ".opus"):
        mime = "audio/ogg"
    return mime or "application/octet-stream"


def supported(mime: str) -> bool:
    return mime in SUPPORTED_EXACT or mime.startswith(SUPPORTED_PREFIXES)


def _get_pool() -> KeyPool:
    global _pool
    with _lock:
        if _pool is None:
            _pool = KeyPool(GEMINI_API_KEYS, "gemini")
        return _pool


def _generate(key: str, model: str, contents: list) -> str:
    """One Gemini call (separate function so tests can replace it)."""
    from google import genai

    with _lock:
        client = _clients.get(key) or _clients.setdefault(key, genai.Client(api_key=key))
    resp = client.models.generate_content(model=model, contents=contents)
    return (resp.text or "").strip()


def _classify(e: Exception) -> tuple[str, float]:
    """-> (action, cooldown) where action is 'skip' (try other model/key), 'disable_key' or 'raise'."""
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    text = str(e)
    if code == 429 or "RESOURCE_EXHAUSTED" in text:
        return "skip", COOLDOWN_DAILY if ("PerDay" in text or "per day" in text.lower()) else COOLDOWN_429
    if code == 404 or "NOT_FOUND" in text or "no longer available" in text:
        return "skip", COOLDOWN_MISSING
    if code in (500, 502, 503, 504) or "UNAVAILABLE" in text or "DEADLINE" in text:
        return "skip", 15
    if code in (401, 403) or "API_KEY_INVALID" in text or "PERMISSION_DENIED" in text:
        return "disable_key", 0
    return "raise", 0


def _cache_get(k):
    with _lock:
        if k in _cache:
            _cache.move_to_end(k)
            return _cache[k]


def _cache_put(k, v):
    with _lock:
        _cache[k] = v
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def analyze(path: Path, prompt: str | None = None) -> str:
    """Ask Gemini about a local file. Raises RuntimeError with a readable reason if every model/key fails."""
    from google.genai import types

    mime = guess_mime(path)
    if not supported(mime):
        raise ValueError(f"Gemini can't analyse {mime} files")
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        raise ValueError("File is larger than 20 MB")
    data = path.read_bytes()
    prompt = prompt or DEFAULT_PROMPTS.get(mime.split("/")[0], DEFAULT_PROMPTS["application"])

    ck = hashlib.sha256(data).hexdigest() + "|" + prompt
    hit = _cache_get(ck)
    if hit is not None:
        return hit

    contents = [types.Part.from_bytes(data=data, mime_type=mime), prompt]
    pool = _get_pool()
    last_error, waited = None, False
    while True:
        soonest = None
        for model in GEMINI_VISION_MODELS:               # preferred model first
            for _ in range(len(pool.keys)):
                try:
                    index, key = pool.acquire()
                except RuntimeError:
                    break
                ready_in = _model_cool.get((index, model), 0) - time.monotonic()
                if ready_in > 0:
                    soonest = ready_in if soonest is None else min(soonest, ready_in)
                    continue
                try:
                    text = _generate(key, model, contents) or "(Gemini returned no text)"
                    _cache_put(ck, text)
                    return text
                except Exception as e:
                    action, cool = _classify(e)
                    if action == "raise":
                        raise
                    last_error = e
                    print(f"[gemini] {model} key #{index + 1}: {type(e).__name__} -> {action}")
                    if action == "disable_key":
                        pool.disable(index)
                    else:
                        _model_cool[(index, model)] = time.monotonic() + cool
                        soonest = cool if soonest is None else min(soonest, cool)
        # everything failed or is cooling down: wait once if it is short, else give up
        if soonest is not None and soonest <= MAX_WAIT and not waited:
            waited = True
            time.sleep(soonest + 0.5)
            continue
        raise RuntimeError(
            "Gemini is rate limited or unavailable for all configured models/keys"
            + (f" (last error: {type(last_error).__name__})" if last_error else "")
            + ". Try again in a minute.")

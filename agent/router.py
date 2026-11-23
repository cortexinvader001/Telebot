"""Cost control: decide whether a message needs the full agent, and keep re-sent history small.

Agnes bills/limits per request and re-sends the whole context on every request, so the biggest savings are:
  * simple chat -> cheap model, NO tool schemas, tiny system prompt, 1 request
  * old tool outputs shrunk before they are re-sent on later turns
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from settings import BOT_NAME, TIMEZONE

ESCALATE = "ESCALATE"
MAX_SIMPLE_CHARS = 400
FAST_HISTORY = 10          # plain user/assistant messages given to the fast model
OLD_TOOL_CHARS = 500       # tool outputs from earlier turns are cut to this

# Words that almost always mean "needs a tool". Leaning towards "simple" is fine: the fast model can ESCALATE.
_NEEDS_TOOLS = re.compile(
    r"\b(search|look ?up|google|latest|news|today|tonight|currently|price of|weather|score|stock|exchange rate|"
    r"download|install|run|execute|script|code|file|files|pdf|docx?|xlsx?|csv|chart|graph|plot|image|photo|picture|"
    r"convert|compress|zip|ffmpeg|video|audio|voice|send me|attach|generate|build|create|draft|summari[sz]e|"
    r"analy[sz]e|read|open|save|remind|schedule|tool|skill|workspace|upload|link|url)\b|https?://|www\.|```|\[user uploaded",
    re.I)


def is_simple(query: str, history: list[dict]) -> bool:
    q = query.strip()
    if not q or len(q) > MAX_SIMPLE_CHARS or "\n\n" in q:
        return False
    if _NEEDS_TOOLS.search(q):
        return False
    # follow-ups like "yes" / "continue" / "do it" belong to a tool conversation
    if any(m.get("tool_calls") or m.get("role") == "tool" for m in history[-6:]):
        return False
    return True


def short_prompt() -> str:
    now = datetime.now(ZoneInfo(TIMEZONE)).strftime("%A %Y-%m-%d %H:%M")
    return (f"You are {BOT_NAME}, an assistant in Telegram. Be strict and short; lead with the answer; reply in the user's language. "
            f"Now: {now}. You have NO tools. If the request needs web search, up-to-date facts, files, uploads, code execution, "
            f"images, or any real action, reply with exactly {ESCALATE} and nothing else.")


def plain_history(history: list[dict], n: int = FAST_HISTORY) -> list[dict]:
    """Only user/assistant text (no tool calls/results), starting with a user message, for the tool-less fast model."""
    out = [{"role": m["role"], "content": m["content"]} for m in history
           if m.get("role") in ("user", "assistant") and m.get("content") and not m.get("tool_calls")]
    out = out[-n:]
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def compact(history: list[dict]) -> list[dict]:
    """Shrink tool outputs from earlier turns (they are re-sent with every request). Returns copies."""
    out = []
    for m in history:
        c = m.get("content")
        if m.get("role") == "tool" and isinstance(c, str) and len(c) > OLD_TOOL_CHARS:
            m = {**m, "content": c[:OLD_TOOL_CHARS] + '..."[older tool output truncated; call the tool again if needed]"'}
        out.append(m)
    return out

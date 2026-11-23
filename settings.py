"""Central settings. Secrets come from the environment / .env ONLY (no hardcoded fallbacks)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# Everything that must survive restarts lives under DATA_DIR (point it at a persistent disk, e.g. /data on Render).
DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_ROOT = DATA_DIR / "workspace"
CUSTOM_TOOLS_DIR = DATA_DIR / "custom_tools"
SKILLS_DIR = ROOT / "skills"
AGENT_DB = DATA_DIR / "agent_memory.db"

BOT_NAME = os.getenv("BOT_NAME", "Axion")
TIMEZONE = os.getenv("TIMEZONE", "Africa/Lagos")

def env_list(*names: str) -> list[str]:
    """Comma/space/newline separated values from the first set variable(s); de-duplicated, order kept."""
    out: list[str] = []
    for name in names:
        for part in (os.getenv(name) or "").replace("\n", ",").replace(" ", ",").split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


# LLM brain (OpenAI-compatible). AGNES_API_KEYS="k1,k2,k3" (AGNES_API_KEY is also accepted).
AGNES_API_KEYS = env_list("AGNES_API_KEYS", "AGNES_API_KEY")
AGNES_BASE_URL = os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1")
AGNES_MODEL = os.getenv("AGNES_MODEL", "agnes-2.5-flash")            # agent brain: tools, reasoning, long context
# Agnes has no auto-routing (each model is picked by ID), so the bot routes itself: simple chat goes to this cheaper
# model with no tools and a tiny prompt; anything needing tools/files/web escalates to AGNES_MODEL.
AGNES_FAST_MODEL = os.getenv("AGNES_FAST_MODEL", "agnes-1.5-flash")
AGNES_ROUTER = os.getenv("AGNES_ROUTER", "1") == "1"

# Gemini (vision / audio / pdf understanding)
# Tried in order; a model that is rate limited (429), missing (404) or overloaded (5xx) is skipped for a while.
# Each model has its own quota, so the chain doubles as 429 backup.
GEMINI_VISION_MODELS = env_list("GEMINI_VISION_MODELS", "GEMINI_VISION_MODEL") or [
    "gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
GEMINI_VISION_MODEL = GEMINI_VISION_MODELS[0]
# NOTE: Google applies Gemini limits per Google Cloud *project*, so extra keys only help if they come from different projects.
GEMINI_API_KEYS = env_list("GEMINI_API_KEYS", "GEMINI_API_KEY")

# Shell sandbox: when the bot runs as root (Docker) commands are dropped to this unprivileged user.
SANDBOX_UID = int(os.getenv("SANDBOX_UID", "0") or 0)
SANDBOX_GID = int(os.getenv("SANDBOX_GID", "0") or 0)

# Agent limits
MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "15"))        # model calls per user turn
MAX_HISTORY = int(os.getenv("AGENT_MAX_HISTORY", "60"))    # messages reloaded per turn
MAX_TOOL_CHARS = int(os.getenv("AGENT_MAX_TOOL_CHARS", "8000"))
MAX_CUSTOM_TOOLS = 50
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # Telegram Bot API download limit


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

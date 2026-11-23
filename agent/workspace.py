"""Per-chat workspace + safe path resolution for the file tools."""
import os
import re
from pathlib import Path

from context import current_chat_id
from agent import sandbox
from settings import SANDBOX_GID, SANDBOX_UID, SKILLS_DIR, WORKSPACE_ROOT


def chat_dir() -> Path:
    chat_id = current_chat_id.get()
    name = "shared" if chat_id is None else "chat_" + re.sub(r"[^0-9A-Za-z_-]", "_", str(chat_id))
    path = WORKSPACE_ROOT / name
    (path / "uploads").mkdir(parents=True, exist_ok=True)
    path = path.resolve()
    share(path), share(path / "uploads")
    return path


def resolve(path: str, *, read_only_ok: bool = False) -> Path:
    """Resolve `path` (relative to the chat workspace) and refuse anything outside it.

    Symlinks are resolved first, so a link pointing out of the workspace is rejected.
    With read_only_ok=True the skills directory is also readable.
    """
    base = chat_dir()
    p = Path(path).expanduser()
    p = (p if p.is_absolute() else base / p).resolve()
    allowed = [base] + ([SKILLS_DIR.resolve()] if read_only_ok else [])
    if not any(p == a or a in p.parents for a in allowed):
        raise PermissionError(f"Path is outside your workspace: {path}")
    return p


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(chat_dir()))
    except ValueError:
        return str(path)


def share(path: Path) -> None:
    """When shell commands run as another user, give them ownership of what the bot creates in the workspace."""
    if sandbox.dropping():
        try:
            os.chown(path, SANDBOX_UID, SANDBOX_GID or SANDBOX_UID)
        except OSError:
            pass


def share_upwards(path: Path) -> None:
    """share() `path` and every parent directory inside the chat workspace."""
    base = chat_dir()
    p = path.resolve()
    while p != base and base in p.parents:
        share(p)
        p = p.parent

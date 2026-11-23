import os

from agent import guard, sandbox
from agent.notify import make_notifier
from agent.workspace import chat_dir
from context import current_chat_id

from .base import schema

SCHEMA = schema(
    "shell",
    "Run a shell command in this chat's workspace. Use it for python scripts, pip/npm installs, ffmpeg, git, "
    "data processing, etc. No secrets in the environment. Default timeout 30s, max 300s. "
    "Inside the command, `say \"text\"` (or `echo \"::say:: text\"`) sends that text to the user immediately; "
    "use it for short progress/result notes. Dangerous commands are blocked; destructive ones need confirmed=true "
    "(only after the user said yes in chat).",
    {
        "command": {"type": "string", "description": "Command to execute."},
        "timeout_seconds": {"type": "integer", "description": "Optional timeout, 1-300."},
        "confirmed": {"type": "boolean", "description": "True ONLY if the user explicitly approved this exact action."},
    },
    ["command"],
)

# `say` as a shell function works even if bin/say lost its exec bit; bin/say covers child scripts.
_PRELUDE = "say() { printf '%s %s\\n' '::say::' \"$*\"; }\n"


def run(args):
    command = (args.get("command") or "").strip()
    if not command:
        return {"error": "Empty command"}
    verdict = guard.check(command)
    if verdict and not (verdict[0] == "confirm" and args.get("confirmed") is True):
        return guard.blocked(*verdict)

    timeout = max(1, min(int(args.get("timeout_seconds") or 30), 300))
    notify = make_notifier(current_chat_id.get())
    full = (_PRELUDE + command) if os.name == "posix" else command
    result = sandbox.run(full, shell=True, cwd=chat_dir(), timeout=timeout, on_say=notify)
    if notify.state["sent"]:
        result["sent_to_user"] = notify.state["sent"]
        if notify.state["dropped"]:
            result["say_limit_hit"] = f"{notify.state['dropped']} more say lines were dropped (max 10 per command)"
    if result["timed_out"]:
        result["error"] = f"Command timed out after {timeout}s and was killed"
    return result


TOOLS = {"shell": (SCHEMA, run)}

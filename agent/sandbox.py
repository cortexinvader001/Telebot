"""Run subprocesses with a stripped environment, a timeout and process-group kill.

NOTE: this removes secrets from the environment and confines the *working directory*,
it is NOT a security boundary. For real isolation run the whole bot in a container.
"""
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from settings import ROOT, SANDBOX_GID, SANDBOX_UID

MARKER = "::say::"
_SAFE_ENV = ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "TEMP", "TMP")


def dropping() -> bool:
    """True when the bot runs as root (Docker) and shell commands are run as an unprivileged user.
    This is what stops commands from reading the bot's API keys via /proc/<pid>/environ."""
    return os.name == "posix" and os.geteuid() == 0 and SANDBOX_UID > 0


def tool_path() -> str:
    """PATH for sandboxed commands: bundled bin/ first, then the bot's own interpreter, then the system PATH."""
    return os.pathsep.join([str(ROOT / "bin"), str(Path(sys.executable).parent), os.environ.get("PATH", "")])


def clean_env(home: Path) -> dict:
    env = {k: os.environ[k] for k in _SAFE_ENV if k in os.environ}
    env["PATH"] = os.pathsep.join([str(home / ".local" / "bin"), str(home / "node_modules" / ".bin"), tool_path()])
    env["HOME"] = str(home)
    env["PYTHONUNBUFFERED"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _pump(stream, sink: list, on_say):
    for line in iter(stream.readline, ""):
        stripped = line.lstrip()
        if on_say and stripped.startswith(MARKER):
            on_say(stripped[len(MARKER):])
        else:
            sink.append(line)


def run(cmd, *, shell: bool, cwd: Path, timeout: int, stdin: str | None = None, on_say=None) -> dict:
    """Run a command. Output lines starting with ::say:: are passed to on_say() *while it runs*
    (and removed from the captured output)."""
    posix = os.name == "posix"
    p = subprocess.Popen(
        cmd, shell=shell, cwd=cwd, env=clean_env(cwd),
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace", bufsize=1,
        start_new_session=posix,
        **({"user": SANDBOX_UID, "group": SANDBOX_GID or SANDBOX_UID, "extra_groups": []} if dropping() else {}),
    )
    out, err = [], []
    threads = [threading.Thread(target=_pump, args=(p.stdout, out, on_say), daemon=True),
               threading.Thread(target=_pump, args=(p.stderr, err, on_say), daemon=True)]
    for t in threads:
        t.start()
    if stdin is not None:
        try:
            p.stdin.write(stdin)
            p.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    timed_out = False
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(p.pid, signal.SIGKILL) if posix else p.kill()
        except ProcessLookupError:
            pass
        p.wait()
    for t in threads:  # a background child may keep the pipe open; don't wait forever
        t.join(timeout=2)
    return {
        "stdout": "".join(out)[-6000:],
        "stderr": "".join(err)[-3000:],
        "returncode": p.returncode,
        "timed_out": timed_out,
    }

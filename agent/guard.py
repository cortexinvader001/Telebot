"""Seatbelt for the shell tool: refuses clearly dangerous commands, asks for confirmation on destructive ones.

This is pattern matching, so it is NOT a security boundary (a determined model can obfuscate).
It catches the honest mistakes; use a container for real isolation.
"""
import re
import shlex

_CMD = r"(?:^|[;&|(`]|&&|\|\|)\s*"  # start of a command

HARD = [  # never allowed
    (_CMD + r"sudo\b|" + _CMD + r"su\s", "privilege escalation (sudo/su)"),
    (_CMD + r"(apt|apt-get|yum|dnf|apk|brew|snap|pacman|zypper)\s", "system package managers are not allowed; use pip or npm"),
    (r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b", "piping a download into a shell"),
    (_CMD + r"(nmap|masscan|zmap|nikto|sqlmap|hydra|hashcat|msfconsole|aircrack-ng|nuclei|gobuster|dirb|wpscan)\b",
     "scanning / attack tools; only touch systems the user owns"),
    (_CMD + r"(ssh|scp|sftp|nc|ncat|netcat|telnet)\s", "remote access tools"),
    (r"\bmkfs(\.\w+)?\b|\bdd\s+if=|:\(\)\s*\{|>\s*/dev/sd", "disk-destroying command"),
    (_CMD + r"(shutdown|reboot|poweroff|halt|systemctl)\b", "system control"),
    (r"\b(npm|pnpm|yarn)\s+(install|i|add)\b[^;&|]*\s(-g|--global)\b", "global installs are not allowed"),
]

CONFIRM = [  # allowed only with confirmed=true (user must have said yes in chat)
    (r"\bgit\s+push\b", "git push publishes changes"),
    (r"\bgit\s+(reset\s+--hard|clean\s|branch\s+-D)", "destructive git operation"),
]


def _risky_rm(command: str) -> bool:
    for m in re.finditer(_CMD + r"rm\s+([^;&|]*)", command):
        try:
            tokens = shlex.split(m.group(1))
        except ValueError:
            return True
        flags = "".join(t[1:] for t in tokens if t.startswith("-") and not t.startswith("--")) + \
                "".join("r" if t == "--recursive" else "f" if t == "--force" else "" for t in tokens)
        targets = [t for t in tokens if not t.startswith("-")]
        if not ({"r", "R", "f"} & set(flags)):
            continue
        for t in targets:
            if t in ("/", "~", ".", "..", "*", "/*") or t.startswith(("/", "~", "$HOME", "${HOME}")) or ".." in t.split("/"):
                return True
    return False


def check(command: str):
    """-> None if fine, else ('hard'|'confirm', reason)."""
    for pattern, reason in HARD:
        if re.search(pattern, command):
            return "hard", reason
    for pattern, reason in CONFIRM:
        if re.search(pattern, command):
            return "confirm", reason
    if _risky_rm(command):
        return "confirm", "recursive/forced delete outside a plain workspace file"
    return None


def blocked(level: str, reason: str) -> dict:
    if level == "hard":
        return {"blocked": True, "reason": reason,
                "instruction": "This action is not allowed. Do NOT retry it or work around it. Tell the user what was blocked and why."}
    return {"blocked": True, "needs_confirmation": True, "reason": reason,
            "instruction": "Describe exactly what you would do and ask the user to confirm, then STOP. Only after they reply yes "
                           "in the chat may you call again with confirmed=true. Do not work around this."}

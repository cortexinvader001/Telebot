"""SQLite persistence for agent conversations (survives restarts, shared by all code paths)."""
import json
import os
import sqlite3
import threading

from settings import AGENT_DB, MAX_HISTORY

KEEP_ROWS = 300
_init_lock = threading.Lock()
_ready = False


def _db():
    global _ready
    db = sqlite3.connect(AGENT_DB, timeout=10)
    if not _ready:
        with _init_lock:
            db.execute(
                """CREATE TABLE IF NOT EXISTS agent_messages (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       chat_id TEXT NOT NULL,
                       message TEXT NOT NULL,
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_agent_chat ON agent_messages(chat_id, id)")
            db.commit()
            try:
                os.chmod(AGENT_DB, 0o600)  # the sandboxed shell must not be able to read chat history
            except OSError:
                pass
            _ready = True
    return db


def sanitize(messages: list[dict]) -> list[dict]:
    """Make a history slice valid for the chat API.

    Starts at a user message, and drops assistant tool-call messages whose tool results
    are missing (e.g. a crash mid-turn) as well as orphaned tool messages.
    """
    i = 0
    while i < len(messages) and messages[i].get("role") != "user":
        i += 1
    msgs, out = messages[i:], []
    j = 0
    while j < len(msgs):
        m = msgs[j]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            ids = {tc["id"] for tc in m["tool_calls"]}
            k = j + 1
            results = []
            while k < len(msgs) and msgs[k].get("role") == "tool":
                results.append(msgs[k])
                k += 1
            if ids <= {r.get("tool_call_id") for r in results}:
                out.append(m)
                out.extend(results)
            j = k
        elif m.get("role") == "tool":
            j += 1  # orphan
        else:
            out.append(m)
            j += 1
    return out


def load(chat_id, limit: int = MAX_HISTORY) -> list[dict]:
    with _db() as db:
        rows = db.execute(
            "SELECT message FROM agent_messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (str(chat_id), limit),
        ).fetchall()
    return sanitize([json.loads(r[0]) for r in reversed(rows)])


def append_many(chat_id, messages: list[dict]) -> None:
    if not messages:
        return
    with _db() as db:
        db.executemany(
            "INSERT INTO agent_messages (chat_id, message) VALUES (?, ?)",
            [(str(chat_id), json.dumps(m, default=str)) for m in messages],
        )
        db.execute(
            """DELETE FROM agent_messages WHERE chat_id=? AND id NOT IN (
                   SELECT id FROM agent_messages WHERE chat_id=? ORDER BY id DESC LIMIT ?)""",
            (str(chat_id), str(chat_id), KEEP_ROWS),
        )


def clear(chat_id) -> None:
    with _db() as db:
        db.execute("DELETE FROM agent_messages WHERE chat_id=?", (str(chat_id),))

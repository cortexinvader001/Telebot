"""Lets shell commands / custom tools talk to the user while they run (via the ::say:: marker)."""
import threading

from tg import get_bot

MAX_PER_COMMAND = 10
MAX_LEN = 500


def make_notifier(chat_id):
    """Returns notify(text) bound to one chat, rate-limited per command. Safe to call from any thread."""
    lock = threading.Lock()
    state = {"sent": [], "dropped": 0}

    def notify(text: str):
        text = text.strip()[:MAX_LEN]
        if not text:
            return
        with lock:
            if len(state["sent"]) >= MAX_PER_COMMAND:
                state["dropped"] += 1
                return
            state["sent"].append(text)
        try:
            get_bot().send_message(chat_id, text)
        except Exception as e:
            print(f"SAY ERROR: {e!r}")

    notify.state = state
    return notify

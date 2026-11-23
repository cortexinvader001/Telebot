"""Single shared TeleBot instance (so tools never need to import bot.py)."""
import threading

import telebot

from settings import env

_bot = None
_lock = threading.Lock()


def get_bot() -> telebot.TeleBot:
    global _bot
    with _lock:
        if _bot is None:
            # num_threads > 2 so a long agent run doesn't block every other chat
            _bot = telebot.TeleBot(env("TELEGRAM_TOKEN", required=True), num_threads=8)
        return _bot

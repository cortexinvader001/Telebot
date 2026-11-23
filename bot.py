import contextlib
import json
import threading

import telegramify_markdown

from agent import clitools, uploads
from agent.core import agent as run_agent
from commands import basic
from commands.gemini import gemini
from context import current_chat_id
from settings import ROOT, env
from tg import get_bot

with open(ROOT / "config.json", "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

CHUNK = 3000  # raw characters per Telegram message (MarkdownV2 escaping adds overhead; hard limit is 4096)


def split_text(text: str, size: int = CHUNK) -> list[str]:
    chunks = []
    while len(text) > size:
        cut = max(text.rfind("\n\n", 0, size), text.rfind("\n", 0, size), text.rfind(" ", 0, size))
        cut = cut if cut > size // 2 else size
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text.strip():
        chunks.append(text)
    return chunks


class Status:
    """One 'working on it' message that is edited as tools run, then deleted."""

    def __init__(self, bot, chat_id):
        self.bot, self.chat_id, self.msg, self.last = bot, chat_id, None, None

    def __call__(self, text):
        if text == self.last:
            return
        self.last = text
        try:
            if self.msg is None:
                self.msg = self.bot.send_message(self.chat_id, text)
            else:
                self.bot.edit_message_text(text, self.chat_id, self.msg.message_id)
        except Exception:
            pass

    def clear(self):
        if self.msg is not None:
            try:
                self.bot.delete_message(self.chat_id, self.msg.message_id)
            except Exception:
                pass


@contextlib.contextmanager
def typing(bot, chat_id):
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                bot.send_chat_action(chat_id, "typing")
            except Exception:
                pass
            stop.wait(4)

    threading.Thread(target=loop, daemon=True).start()
    try:
        yield
    finally:
        stop.set()


class MyBot:
    def __init__(self):
        self.bot = get_bot()
        self.commands = {
            "start": basic.start, "help": basic.help_cmd, "reset": basic.reset,
            "tools": basic.tools_cmd, "skills": basic.skills_cmd,
        }
        self.register()

    # ---- helpers -------------------------------------------------------------------
    def denied(self, message) -> bool:
        if CONFIG.get("admin_only") and message.from_user.id not in CONFIG.get("admins", []):
            self.bot.reply_to(message, "This bot is restricted to admins.")
            return True
        return False

    def reply(self, message, text: str):
        for chunk in split_text(text or ""):
            try:
                self.bot.reply_to(message, telegramify_markdown.markdownify(chunk), parse_mode="MarkdownV2")
            except Exception:  # formatting rejected by Telegram -> plain text
                self.bot.reply_to(message, chunk)

    def run_agent_turn(self, message, text: str, route: bool = True):
        chat_id = message.chat.id
        status = Status(self.bot, chat_id)
        token = current_chat_id.set(chat_id)
        try:
            with typing(self.bot, chat_id):
                answer = run_agent(text, chat_id, message.from_user.first_name, on_event=status, route=route)
            status.clear()
            self.reply(message, answer)
        except Exception as e:
            print(f"AGENT TURN ERROR: {e!r}")
            status.clear()
            self.bot.reply_to(message, "Something went wrong on my side. Please try again.")  # details stay in the log
        finally:
            current_chat_id.reset(token)

    # ---- handlers ------------------------------------------------------------------
    def register(self):
        bot = self.bot

        @bot.message_handler(commands=list(self.commands))
        def on_command(message):
            if self.denied(message):
                return
            cmd = message.text.split()[0][1:].split("@")[0]
            self.reply(message, self.commands[cmd](message))

        @bot.message_handler(commands=["agent"])
        def on_agent(message):
            if self.denied(message):
                return
            text = message.text.partition(" ")[2].strip()
            if not text:
                return self.reply(message, "Usage: /agent <what you want me to do>")
            self.run_agent_turn(message, text, route=False)  # explicit /agent = full agent

        @bot.message_handler(commands=["gemini"])
        def on_gemini(message):
            if self.denied(message):
                return
            token = current_chat_id.set(message.chat.id)
            try:
                with typing(bot, message.chat.id):
                    self.reply(message, gemini(message, message.text.partition(" ")[2].strip()))
            except Exception as e:
                print(f"GEMINI ERROR: {e!r}")
                bot.reply_to(message, "Gemini request failed.")
            finally:
                current_chat_id.reset(token)

        @bot.message_handler(content_types=["text"])
        def on_text(message):
            if self.denied(message):
                return
            text = message.text
            # replying to a message that carried a file -> include that file
            quoted = getattr(message, "reply_to_message", None)
            if quoted is not None and quoted.content_type in uploads.MEDIA_TYPES:
                token = current_chat_id.set(message.chat.id)
                try:
                    with typing(bot, message.chat.id):
                        block = uploads.ingest(quoted)
                finally:
                    current_chat_id.reset(token)
                if block:
                    text = f"{block}\n\nUser message: {text}"
            self.run_agent_turn(message, text)

        @bot.message_handler(content_types=uploads.MEDIA_TYPES)
        def on_media(message):
            if self.denied(message):
                return
            token = current_chat_id.set(message.chat.id)
            try:
                with typing(bot, message.chat.id):
                    block = uploads.ingest(message)
            finally:
                current_chat_id.reset(token)
            if block:
                self.run_agent_turn(message, block)

    def run(self):
        self.bot.infinity_polling(skip_pending=True)


def _serve_health(port: int):
    """Render *web services* must listen on $PORT. Workers don't need this (it is only started when PORT is set)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    HTTPServer(("0.0.0.0", port), Health).serve_forever()


def _check_tools():
    try:
        clitools.ensure(auto_install=env("AUTO_SETUP_TOOLS", "1") == "1")
        print(clitools.report())
    except Exception as e:
        print(f"[tools] check failed: {e}")


if __name__ == "__main__":
    print("BOT INITIALISED...")
    threading.Thread(target=_check_tools, daemon=True).start()  # don't delay startup
    if env("PORT"):
        threading.Thread(target=_serve_health, args=(int(env("PORT")),), daemon=True).start()
    MyBot().run()

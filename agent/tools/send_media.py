from urllib.parse import urlparse

from agent.workspace import resolve
from context import current_chat_id
from tg import get_bot

from .base import schema

SCHEMA = schema(
    "send_media",
    "Send an image, video, audio file or document to the current Telegram chat. "
    "`data` is a workspace file path (e.g. a PDF you generated) or a public http(s) URL.",
    {
        "media_type": {"type": "string", "enum": ["image", "video", "audio", "document"]},
        "data": {"type": "string", "description": "Workspace file path or public URL."},
        "caption": {"type": "string", "description": "Optional caption (max 1000 chars)."},
    },
    ["media_type", "data"],
)


def run(args):
    chat_id = current_chat_id.get()
    if chat_id is None:
        return {"error": "No active chat"}
    bot = get_bot()
    kind, data = args["media_type"], args["data"]
    caption = (args.get("caption") or "")[:1000] or None
    methods = {"image": bot.send_photo, "audio": bot.send_audio, "video": bot.send_video, "document": bot.send_document}
    if kind not in methods:
        return {"error": f"Unsupported media_type: {kind}"}

    if urlparse(data).scheme in ("http", "https"):
        methods[kind](chat_id, data, caption=caption)
        return {"ok": True, "sent": data}

    path = resolve(data)  # workspace only: the agent cannot exfiltrate .env / databases
    if not path.is_file():
        return {"error": f"File not found: {data}"}
    try:
        with open(path, "rb") as f:
            methods[kind](chat_id, f, caption=caption)
    except Exception as e:
        if kind == "image":  # e.g. too large / odd dimensions for sendPhoto -> send as document
            with open(path, "rb") as f:
                bot.send_document(chat_id, f, caption=caption)
        else:
            return {"error": f"Telegram refused the file: {e}"}
    return {"ok": True, "sent": path.name}


TOOLS = {"send_media": (SCHEMA, run)}

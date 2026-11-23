import contextvars
current_chat_id = contextvars.ContextVar("current_chat_id", default=None)
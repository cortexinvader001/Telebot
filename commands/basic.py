from agent import clitools, core, memory, skills, tools
from settings import BOT_NAME

HELP = f"""**{BOT_NAME}**: an AI agent.

Just talk to me, or send photos, documents, PDFs or voice notes.

I can search the web, read/write files, run code, work with PDFs, analyse images (Gemini) and build my own tools when I need one.

Commands:
/help: this message
/reset: forget this chat's conversation
/tools: list my tools
/skills: list my skills
/agent <text>: same as just writing to me"""


def start(message):
    return f"Hi {message.from_user.first_name}! I'm {BOT_NAME}. Send a task, a photo or a file, or /help."


def help_cmd(message):
    return HELP


def reset(message):
    memory.clear(message.chat.id)
    return "Conversation cleared. (Files in my workspace were kept.)"


def tools_cmd(message):
    t = tools.names()
    custom = ", ".join(f"`{n}`" for n in t["custom"]) or "none yet"
    have, missing = clitools.summary()
    cli = f"\n**CLI:** {', '.join(have)}" + (f"\n**Missing CLI:** {', '.join(missing)}" if missing else "")
    return "**Built-in:** " + ", ".join(f"`{n}`" for n in t["builtin"]) + f"\n**Created by me:** {custom}" + cli + f"\n**Routing:** {core.STATS['fast']} quick, {core.STATS['escalated']} escalated, {core.STATS['full']} full agent (since restart)"


def skills_cmd(message):
    s = skills.list_skills()
    return "\n".join(f"- **{x['name']}**: {x['description'][:140]}" for x in s) or "No skills installed."

"""Tool registry: built-in tools plus agent-created custom tools (reloaded on every model call)."""
from . import analyze_file, files, send_media, shell, skills_tool, tool_builder, web

BUILTIN: dict = {}
for _m in (shell, files, web, send_media, analyze_file, skills_tool, tool_builder):
    BUILTIN.update(_m.TOOLS)


def schemas() -> list[dict]:
    custom = tool_builder.custom_schemas()
    return [s for s, _ in BUILTIN.values()] + [s for n, s in custom.items() if n not in BUILTIN]


def names() -> dict:
    return {"builtin": list(BUILTIN), "custom": [n for n in tool_builder.custom_schemas() if n not in BUILTIN]}


def execute(name: str, args: dict):
    if name in BUILTIN:
        return BUILTIN[name][1](args)
    if name in tool_builder.custom_schemas():
        return tool_builder.run_custom(name, args)
    return {"error": f"TOOL NOT FOUND: {name}. Use create_tool if you need this capability."}

"""Lets the agent extend itself: create, list, update and delete its own tools.

A custom tool is custom_tools/<name>.py (defining `run(args) -> JSON-serialisable`) plus
custom_tools/<name>.json (description + parameters). Custom tools ALWAYS execute in a
subprocess with a stripped environment, never inside the bot process.
"""
import ast
import json
import re
import sys
from pathlib import Path

from agent import sandbox
from agent.notify import make_notifier
from agent.workspace import chat_dir
from context import current_chat_id
from settings import CUSTOM_TOOLS_DIR, MAX_CUSTOM_TOOLS

from .base import schema

RUNNER = Path(__file__).resolve().parents[1] / "custom_runner.py"
SENTINEL = "<<RESULT>>"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")


def _py(name):
    return CUSTOM_TOOLS_DIR / f"{name}.py"


def _meta(name):
    return CUSTOM_TOOLS_DIR / f"{name}.json"


def custom_schemas() -> dict:
    """name -> OpenAI tool schema for every valid custom tool on disk."""
    out = {}
    if not CUSTOM_TOOLS_DIR.is_dir():
        return out
    for meta in sorted(CUSTOM_TOOLS_DIR.glob("*.json")):
        try:
            data = json.loads(meta.read_text())
            name = data["name"]
            if _py(name).is_file():
                out[name] = schema(name, "[custom] " + data["description"],
                                   data["parameters"].get("properties", {}), data["parameters"].get("required", []))
        except Exception:
            continue
    return out


def _invoke(path: Path, args: dict | None, check=False, timeout=60) -> dict:
    cmd = [sys.executable, "-I", str(RUNNER), str(path)] + (["--check"] if check else [])
    res = sandbox.run(cmd, shell=False, cwd=chat_dir(), timeout=timeout, stdin=json.dumps(args or {}),
                      on_say=None if check else make_notifier(current_chat_id.get()))
    if res["timed_out"]:
        return {"error": f"Custom tool timed out after {timeout}s"}
    marker = res["stdout"].rfind(SENTINEL)
    if res["returncode"] != 0 or marker == -1:
        return {"error": "Custom tool failed", "stderr": res["stderr"][-1500:], "stdout": res["stdout"][-800:]}
    try:
        return {"result": json.loads(res["stdout"][marker + len(SENTINEL):].strip()), "stdout": res["stdout"][:marker][-1500:]}
    except json.JSONDecodeError as e:
        return {"error": f"Tool returned non-JSON output: {e}"}


def run_custom(name: str, args: dict):
    out = _invoke(_py(name), args)
    return out["result"] if "result" in out and not out.get("stdout") else out


def create_tool(args):
    name = args.get("name", "")
    if not NAME_RE.match(name):
        return {"error": "name must be snake_case, 3-40 chars, start with a letter"}
    from . import BUILTIN  # late import: avoid circular dependency

    if name in BUILTIN:
        return {"error": f"'{name}' is a built-in tool name"}
    existing = {p.stem for p in CUSTOM_TOOLS_DIR.glob("*.json")}
    if name not in existing and len(existing) >= MAX_CUSTOM_TOOLS:
        return {"error": f"Custom tool limit ({MAX_CUSTOM_TOOLS}) reached; delete one first"}

    params = args.get("parameters") or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            return {"error": "parameters must be a JSON object of property schemas"}
    props = params.get("properties", params) if isinstance(params, dict) else {}
    required = args.get("required") or params.get("required", []) if isinstance(params, dict) else []

    code = args.get("code", "")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"error": f"Syntax error in code: {e}"}
    if not any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body):
        return {"error": "code must define a top-level function run(args) that returns a JSON-serialisable value"}

    CUSTOM_TOOLS_DIR.mkdir(exist_ok=True)
    draft = CUSTOM_TOOLS_DIR / f".draft_{name}.py"
    draft.write_text(code, encoding="utf-8")
    try:
        check = _invoke(draft, None, check=True)
        if "error" in check:
            return {"error": "Tool failed to import", **check}
        test = None
        if args.get("test_args") is not None:
            test = _invoke(draft, args["test_args"])
            if "error" in test:
                return {"error": "Tool failed its test call; not saved. Fix the code and call create_tool again.", **test}
        draft.replace(_py(name))
    finally:
        draft.unlink(missing_ok=True)
    _meta(name).write_text(json.dumps({
        "name": name, "description": args.get("description", ""),
        "parameters": {"properties": props, "required": list(required)}}, indent=2))
    out = {"ok": True, "name": name, "note": "Available from your next step onward."}
    if test is not None:
        out["test_result"] = test["result"]
    return out


def list_custom_tools(args):
    return {"tools": [{"name": n, "description": s["function"]["description"]} for n, s in custom_schemas().items()]}


def delete_tool(args):
    name = args.get("name", "")
    if not NAME_RE.match(name) or not _meta(name).exists():
        return {"error": f"No custom tool named '{name}'"}
    _meta(name).unlink()
    _py(name).unlink(missing_ok=True)
    return {"ok": True}


TOOLS = {
    "create_tool": (schema(
        "create_tool",
        "Create (or update) a NEW reusable tool when no existing tool can do what's needed and the capability will likely "
        "be useful again. `code` must define `def run(args): ...` taking a dict and returning something JSON-serialisable. "
        "Rules: stdlib or already-installed packages only; print('::say:: text') sends a progress note to the user; no secrets/env vars available; work with files relative to the "
        "chat workspace; keep it focused. Always pass `test_args` to smoke-test it - a failing tool is not saved. "
        "For one-off jobs just use `shell` instead.",
        {
            "name": {"type": "string", "description": "snake_case tool name"},
            "description": {"type": "string", "description": "What it does and when to use it (shown to you in future)."},
            "parameters": {"type": "object", "description": "JSON-schema 'properties' of the args, e.g. {\"url\": {\"type\": \"string\"}}"},
            "required": {"type": "array", "items": {"type": "string"}},
            "code": {"type": "string", "description": "Python source defining run(args)."},
            "test_args": {"type": "object", "description": "Args for a smoke-test call."},
        },
        ["name", "description", "parameters", "code"]), create_tool),
    "list_custom_tools": (schema("list_custom_tools", "List tools you created earlier."), list_custom_tools),
    "delete_tool": (schema("delete_tool", "Delete a custom tool you created.", {"name": {"type": "string"}}, ["name"]), delete_tool),
}

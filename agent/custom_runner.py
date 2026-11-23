"""Executed in a SUBPROCESS to run one custom tool: python custom_runner.py <tool.py> [--check]

Reads JSON args from stdin, calls run(args), prints the JSON result after a sentinel line so
that any print() output inside the tool cannot corrupt the result.
"""
import importlib.util
import json
import sys

SENTINEL = "<<RESULT>>"


def main():
    path = sys.argv[1]
    spec = importlib.util.spec_from_file_location("custom_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, "run", None)):
        raise SystemExit("custom tool must define run(args)")
    if "--check" in sys.argv:
        print(SENTINEL + json.dumps({"ok": True}))
        return
    args = json.load(sys.stdin)
    print(SENTINEL + json.dumps(mod.run(args), default=str))


if __name__ == "__main__":
    main()

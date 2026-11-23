import json

from agent.workspace import chat_dir, rel, resolve, share_upwards

from .base import schema

MAX_READ = 20000
BINARY_HINT = "Binary file. For images/audio/PDF understanding use analyze_file; otherwise process it with shell."


def _pdf_text(path):
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, 1):
        pages.append(f"--- page {i} ---\n{page.extract_text() or ''}")
    return "\n".join(pages), len(reader.pages)


def _docx_text(path):
    import docx  # python-docx

    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def read_file(args):
    path = resolve(args["path"], read_only_ok=True)
    if not path.is_file():
        return {"error": f"Not a file: {args['path']}"}
    offset = max(0, int(args.get("offset") or 0))
    limit = max(1, min(int(args.get("limit") or MAX_READ), MAX_READ))
    suffix = path.suffix.lower()
    extra = {}
    try:
        if suffix == ".pdf":
            text, n = _pdf_text(path)
            extra["pages"] = n
            if not text.replace("-", "").replace("page", "").strip(" \n0123456789"):
                return {"error": "PDF has no extractable text (scanned?). Use analyze_file or OCR via the pdf skill."}
        elif suffix == ".docx":
            text = _docx_text(path)
        else:
            raw = path.read_bytes()
            if b"\x00" in raw[:4096]:
                return {"error": BINARY_HINT}
            text = raw.decode("utf-8", errors="replace")
    except ImportError as e:
        return {"error": f"Missing library: {e}. Try shell: pip install --user <package>"}
    except Exception as e:  # corrupt files etc.
        return {"error": f"Could not read file: {e}"}
    chunk = text[offset: offset + limit]
    return {
        "path": rel(path), "total_chars": len(text), "offset": offset,
        "truncated": offset + limit < len(text), "content": chunk, **extra,
    }


def write_file(args):
    path = resolve(args["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.get("append") else "w"
    with open(path, mode, encoding="utf-8") as f:
        f.write(args.get("content", ""))
    share_upwards(path)
    return {"ok": True, "path": rel(path), "bytes": path.stat().st_size}


def edit_file(args):
    path = resolve(args["path"])
    if not path.is_file():
        return {"error": f"Not a file: {args['path']}"}
    text = path.read_text(encoding="utf-8")
    old, new = args["old"], args["new"]
    count = text.count(old)
    if count == 0:
        return {"error": "`old` text not found (must match exactly, including whitespace)"}
    if count > 1 and not args.get("replace_all"):
        return {"error": f"`old` occurs {count} times; add more context or set replace_all=true"}
    path.write_text(text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1), encoding="utf-8")
    return {"ok": True, "replacements": count if args.get("replace_all") else 1}


def list_files(args):
    path = resolve(args.get("path") or ".", read_only_ok=True)
    if not path.is_dir():
        return {"error": f"Not a directory: {args.get('path')}"}
    items = []
    for p in sorted(path.rglob("*") if args.get("recursive") else path.iterdir()):
        if len(items) >= 200:
            break
        items.append({"path": rel(p) if chat_dir() in p.parents else str(p),
                      "type": "dir" if p.is_dir() else "file",
                      "size": p.stat().st_size if p.is_file() else None})
    return {"items": items, "truncated": len(items) >= 200}


TOOLS = {
    "read_file": (schema(
        "read_file",
        "Read a file from the workspace. Handles text/code/CSV/JSON, PDF (text per page) and DOCX. "
        "Large files are paged with offset/limit (characters).",
        {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}},
        ["path"]), read_file),
    "write_file": (schema(
        "write_file", "Create or overwrite a text file in the workspace (or append).",
        {"path": {"type": "string"}, "content": {"type": "string"}, "append": {"type": "boolean"}},
        ["path", "content"]), write_file),
    "edit_file": (schema(
        "edit_file", "Replace exact text in an existing workspace file.",
        {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
         "replace_all": {"type": "boolean"}},
        ["path", "old", "new"]), edit_file),
    "list_files": (schema(
        "list_files", "List files in a workspace directory (uploads/ holds the user's uploads).",
        {"path": {"type": "string"}, "recursive": {"type": "boolean"}}), list_files),
}

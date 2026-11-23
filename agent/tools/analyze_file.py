from agent import vision
from agent.workspace import resolve

from .base import schema

SCHEMA = schema(
    "analyze_file",
    "Ask Gemini a question about an image, scanned/complex PDF, audio or video file in the workspace "
    "(e.g. uploads/photo_1.jpg). Use for OCR, describing images, reading charts, transcribing audio. "
    "Uploaded photos are already analysed automatically, but call this again for a different/more specific question.",
    {
        "path": {"type": "string"},
        "question": {"type": "string", "description": "What to find out. Omit for a general description/transcript."},
    },
    ["path"],
)


def run(args):
    path = resolve(args["path"])
    if not path.is_file():
        return {"error": f"File not found: {args['path']}"}
    try:
        return {"analysis": vision.analyze(path, args.get("question"))}
    except Exception as e:
        return {"error": f"Gemini analysis failed: {e}"}


TOOLS = {"analyze_file": (SCHEMA, run)}

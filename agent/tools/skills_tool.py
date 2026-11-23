from agent import skills

from .base import schema

SCHEMA = schema(
    "load_skill",
    "Load the full instructions for a skill (see the skill list in the system prompt). "
    "ALWAYS call this before doing a task a skill covers (e.g. 'pdf' for anything with PDFs). "
    "Extra files mentioned in a skill can be read with read_file using the returned skill_dir path.",
    {"name": {"type": "string"}},
    ["name"],
)


def run(args):
    found = skills.read_skill(args["name"])
    if found is None:
        return {"error": f"Unknown skill '{args['name']}'", "available": [s["name"] for s in skills.list_skills()]}
    if len(found["instructions"]) > 30000:
        found["instructions"] = found["instructions"][:30000] + "\n...[truncated; read SKILL.md with read_file for the rest]"
    return found


TOOLS = {"load_skill": (SCHEMA, run)}

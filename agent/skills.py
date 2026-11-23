"""Skill discovery: skills/<name>/SKILL.md with `name` and `description` frontmatter."""
import re

from settings import SKILLS_DIR


def _parse(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2)
    return meta, body


def list_skills() -> list[dict]:
    out = []
    if SKILLS_DIR.is_dir():
        for d in sorted(SKILLS_DIR.iterdir()):
            f = d / "SKILL.md"
            if f.is_file():
                meta, _ = _parse(f)
                out.append({"name": meta.get("name", d.name), "dir": d.name,
                            "description": meta.get("description", "")})
    return out


def read_skill(name: str):
    for s in list_skills():
        if name in (s["name"], s["dir"]):
            d = SKILLS_DIR / s["dir"]
            _, body = _parse(d / "SKILL.md")
            files = [str(p.relative_to(d)) for p in sorted(d.rglob("*")) if p.is_file() and p.name != "SKILL.md"]
            return {"name": s["name"], "skill_dir": str(d.resolve()), "instructions": body.strip(), "other_files": files}
    return None

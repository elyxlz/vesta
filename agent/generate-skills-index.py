#!/usr/bin/env python3
"""Generate agent/skills-index.json from all SKILL.md files in agent/skills/."""

import json
import pathlib
import re

REGISTRY_DIR = pathlib.Path(__file__).parent / "skills"
OUTPUT_FILE = pathlib.Path(__file__).parent / "skills-index.json"


def parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter between --- markers."""
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    frontmatter = match.group(1)
    result: dict = {}
    lines = frontmatter.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # Collect continuation lines (indented)
            j = i + 1
            while j < len(lines) and lines[j].startswith(" "):
                value = value + " " + lines[j].strip()
                j += 1
            if key:
                result[key] = value
            i = j
        else:
            i += 1
    # Parse tags list if present (simple inline list: tags: [a, b, c])
    if "tags" in result:
        tags_str = result["tags"]
        if tags_str.startswith("[") and tags_str.endswith("]"):
            tags_str = tags_str[1:-1]
            result["tags"] = [t.strip().strip("\"'") for t in tags_str.split(",") if t.strip()]
        else:
            result["tags"] = [tags_str] if tags_str else []
    return result


skills = []

for skill_md in sorted(REGISTRY_DIR.glob("*/SKILL.md")):
    text = skill_md.read_text()
    fm = parse_frontmatter(text)
    name = fm.get("name", skill_md.parent.name)
    description = fm.get("description", "")
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [tags] if tags else []
    skills.append({"name": name, "description": description, "tags": tags})

skills.sort(key=lambda s: s["name"])

OUTPUT_FILE.write_text(json.dumps(skills, indent=2) + "\n")
print(f"Generated {OUTPUT_FILE} with {len(skills)} skills.")

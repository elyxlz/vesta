#!/usr/bin/env python3
"""Generate agent/skills-index.json from all SKILL.md files in agent/skills/."""

import json
import pathlib
import re

REGISTRY_DIR = pathlib.Path(__file__).parent / "skills"
OUTPUT_FILE = pathlib.Path(__file__).parent / "skills-index.json"


def parse_frontmatter(text: str) -> dict:
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    result: dict = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if key:
                result[key] = value
    if "tags" in result:
        tags_str = result["tags"]
        if tags_str.startswith("[") and tags_str.endswith("]"):
            result["tags"] = [t.strip().strip("\"'") for t in tags_str[1:-1].split(",") if t.strip()]
        else:
            result["tags"] = [tags_str] if tags_str else []
    return result


if __name__ == "__main__":
    skills = []
    for skill_md in sorted(REGISTRY_DIR.glob("*/SKILL.md")):
        fm = parse_frontmatter(skill_md.read_text())
        skills.append({
            "name": fm.get("name", skill_md.parent.name),
            "description": fm.get("description", ""),
            "tags": fm.get("tags", []),
        })
    skills.sort(key=lambda s: s["name"])
    OUTPUT_FILE.write_text(json.dumps(skills, indent=2) + "\n")
    print(f"Generated {OUTPUT_FILE} with {len(skills)} skills.")

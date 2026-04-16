#!/usr/bin/env python3
"""Generate index.json from all SKILL.md files in agent/skills/*."""

import json
import pathlib
import re

SKILLS_DIR = pathlib.Path(__file__).parent
CORE_SKILLS_DIR = pathlib.Path(__file__).parent.parent / "core" / "skills"
OUTPUT_FILE = pathlib.Path(__file__).parent / "index.json"

if __name__ == "__main__":
    skills = []
    skill_mds = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    if CORE_SKILLS_DIR.exists():
        skill_mds = sorted(CORE_SKILLS_DIR.glob("*/SKILL.md")) + skill_mds
    for skill_md in skill_mds:
        skill_name = skill_md.parent.name
        text = skill_md.read_text()
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        fm = dict(re.findall(r"^(\w[\w-]*)\s*:\s*(.+)$", match.group(1), re.MULTILINE)) if match else {}
        skills.append({"name": fm.get("name", skill_name), "description": fm.get("description", "")})
    OUTPUT_FILE.write_text(json.dumps(skills, indent=2) + "\n")
    print(f"Generated {OUTPUT_FILE} with {len(skills)} skills.")

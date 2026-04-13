"""Tests for deployment structure: skills directories, frontmatter, index."""

import json
import re
from pathlib import Path


def test_deployment_structure():
    source_root = Path(__file__).parent.parent
    assert source_root.is_dir()

    skills_dir = source_root / "skills"
    assert skills_dir.is_dir(), "skills/ directory missing"

    expected_skills = [
        "tasks",
        "upstream",
        "dream",
        "what-day",
        "browser",
        "skills-registry",
        "google",
        "microsoft",
        "whatsapp",
        "whisper",
        "zoom",
        "keeper",
        "onedrive",
    ]
    for skill_name in expected_skills:
        assert (skills_dir / skill_name).is_dir(), f"Skill '{skill_name}' missing from skills/"

    for skill_name in ("tasks",):
        assert (skills_dir / skill_name / "cli" / "pyproject.toml").exists(), f"pyproject.toml missing for {skill_name}"

    assert (skills_dir / "whatsapp" / "cli" / "go.mod").exists(), "go.mod missing for whatsapp"


def test_skill_frontmatter():
    skills_dir = Path(__file__).parent.parent / "skills"
    for skill_md in skills_dir.glob("*/SKILL.md"):
        text = skill_md.read_text()
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match, f"{skill_md}: missing frontmatter"
        fm = dict(re.findall(r"^(\w[\w-]*)\s*:\s*(.+)$", match.group(1), re.MULTILINE))
        assert fm.get("name"), f"{skill_md}: missing 'name' in frontmatter"
        assert fm.get("description"), f"{skill_md}: missing 'description' in frontmatter"
        assert fm["name"] == skill_md.parent.name, (
            f"{skill_md}: frontmatter name '{fm['name']}' must match directory name '{skill_md.parent.name}'"
        )


def test_skills_index_valid():
    skills_dir = Path(__file__).parent.parent / "skills"
    index = json.loads((skills_dir / "index.json").read_text())
    assert isinstance(index, list) and index, "skills/index.json must be a non-empty list"
    skill_names = {s["name"] for s in index}
    default_skills_path = skills_dir / "default-skills.txt"
    default_skills = set(default_skills_path.read_text().splitlines()) if default_skills_path.exists() else set()
    for skill_md in skills_dir.glob("*/SKILL.md"):
        text = skill_md.read_text()
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        fm = dict(re.findall(r"^(\w[\w-]*)\s*:\s*(.+)$", match.group(1), re.MULTILINE)) if match else {}
        skill_dir_name = skill_md.parent.name
        name = fm.get("name", skill_dir_name)
        if name in default_skills:
            continue
        assert name in skill_names, f"{skill_dir_name} missing from skills/index.json"


def test_no_em_or_en_dashes_in_prompt_and_skill_files():
    """All prompt, skill, and memory markdown files must be free of em/en dashes."""
    agent_root = Path(__file__).resolve().parent.parent

    md_globs = [
        (agent_root, "MEMORY.md"),
        (agent_root / "skills", "*/SKILL.md"),
        (agent_root / "skills", "*/SETUP.md"),
        (agent_root / "skills", "*/PHONE_NUMBER.md"),
        (agent_root / "prompts", "**/*.md"),
    ]

    em_dash = "\u2014"
    en_dash = "\u2013"

    files: list[Path] = []
    for base, pattern in md_globs:
        files.extend(base.glob(pattern))
    files = sorted(set(files))
    assert files, "No markdown files found - glob patterns may be wrong"

    violations: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if em_dash in line or en_dash in line:
                rel = path.relative_to(agent_root.parent)
                violations.append(f"  {rel}:{lineno}: {line.strip()[:120]}")

    assert not violations, (
        "Em dash (\u2014) or en dash (\u2013) found in markdown files. Use hyphens (-) or rewrite the sentence.\n"
        + "\n".join(violations)
    )


def test_skills_registry_scripts_executable():
    scripts_dir = Path(__file__).parent.parent / "skills" / "skills-registry" / "scripts"
    for script in scripts_dir.iterdir():
        assert script.stat().st_mode & 0o111, f"{script.name} is not executable"

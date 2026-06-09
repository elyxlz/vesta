#!/usr/bin/env python3
"""Guard: every NEWLY added default skill must ship a migration that installs it.

A skill added to `agent/skills/default-skills.txt` ships on fresh vestas (the
Docker image is built from that list), but EXISTING vestas only converge via the
prompt-migration runner (`agent/core/migrations/*.md`). Forgetting the migration
silently strands every existing box without the new default skill.

This catches exactly that, and only that: it diffs `default-skills.txt` against a
base ref and, for each ADDED skill name, requires some migration markdown to run
`skills-install <name>`. Removing or reordering skills is fine; only additions
need a migration.

Usage:
    check-default-skill-migrations.py [BASE_REF]

BASE_REF defaults to $BASE_REF, then origin/master. If the base ref can't be
resolved (e.g. a shallow local checkout with no remote), the check skips with a
warning rather than failing, so it never blocks local work; CI passes the real
base so the guard is enforced there.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SKILLS = REPO_ROOT / "agent" / "skills" / "default-skills.txt"
MIGRATIONS_DIR = REPO_ROOT / "agent" / "core" / "migrations"


def _run(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout


def _resolve_base(argv: list[str]) -> str | None:
    import os

    base = argv[1] if len(argv) > 1 else os.environ.get("BASE_REF", "origin/master")
    code, _ = _run(["git", "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"])
    return base if code == 0 else None


def _added_skills(base: str) -> list[str]:
    """Skill names added to default-skills.txt relative to `base` (added '+' lines)."""
    code, out = _run(["git", "diff", "--unified=0", base, "--", str(DEFAULT_SKILLS)])
    if code != 0:
        return []
    added: list[str] = []
    for line in out.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            name = line[1:].strip()
            if name:
                added.append(name)
    return added


def _migrations_text() -> str:
    if not MIGRATIONS_DIR.exists():
        return ""
    return "\n".join(p.read_text() for p in MIGRATIONS_DIR.glob("*.md"))


def main(argv: list[str]) -> int:
    base = _resolve_base(argv)
    if base is None:
        print("check-default-skill-migrations: base ref unavailable, skipping (CI passes the real base).")
        return 0

    added = _added_skills(base)
    if not added:
        print(f"check-default-skill-migrations: no default skills added vs {base}. OK.")
        return 0

    migrations = _migrations_text()
    missing = [name for name in added if f"skills-install {name}" not in migrations]
    if missing:
        print("ERROR: default skill(s) added without a migration to install them on EXISTING vestas:")
        for name in missing:
            print(f"  - {name}: add a migration under agent/core/migrations/ that runs `skills-install {name}`")
        print("\nFresh vestas get the skill from the image build, but existing boxes only converge")
        print("via the migration runner. See agent/core/migrations/2026-06-account-default-skill.md.")
        return 1

    print(f"check-default-skill-migrations: added {added}, each has an install migration. OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

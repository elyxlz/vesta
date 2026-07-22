#!/usr/bin/env bash
# Rebuild ~/.claude/skills, the symlink farm Claude Code discovers skills from. This is
# the one activation gate: every core skill is always linked; an optional skill under
# agent/skills/ is linked only when listed in data/active-skills.txt. All optional
# skills sit on disk (the workspace is a full checkout), so presence never means active -
# the list does. Run at every container boot before the SDK session starts, and by
# skills-activate / skills-deactivate.
set -euo pipefail
cd ~

SKILLS_DIR="agent/skills"
CORE_SKILLS_DIR="agent/core/skills"
ACTIVE="agent/data/active-skills.txt"
DEFAULTS="agent/core/default-skills.txt"
LINK_DIR="$HOME/.claude/skills"

mkdir -p agent/data

# LEGACY(remove-when: the 2026-08-flat-checkout migration is fleet-applied): a cone box on its
# first flat boot has no active-skills.txt yet and only its coned skills on disk. Seed the list
# from the cone so those skills stay active through the conversion boot, before the migration
# captures them. A flat box has no sparse-checkout file, so this never fires there.
if [ ! -f "$ACTIVE" ] && [ -f .git/info/sparse-checkout ]; then
  git sparse-checkout list 2>/dev/null | sed -n 's#^agent/skills/##p' | sort -u > "$ACTIVE" || true
fi

# Seed the active list from the shipped defaults on first boot, then union any
# newly-shipped default in on later boots, so an upgrade's new default activates before
# the session starts (no boot turn, no restart). A default the user removed reappears -
# same behavior as the old on-disk reconciler.
[ -f "$ACTIVE" ] || : > "$ACTIVE"
if [ -s "$ACTIVE" ] && [ -n "$(tail -c 1 "$ACTIVE")" ]; then
  printf '\n' >> "$ACTIVE"
fi
if [ -f "$DEFAULTS" ]; then
  while IFS= read -r name || [ -n "$name" ]; do
    [ -n "$name" ] || continue
    grep -qxF "$name" "$ACTIVE" || printf '%s\n' "$name" >> "$ACTIVE"
  done < "$DEFAULTS"
fi

# Rebuilt from scratch each run so a deactivated skill leaves no dangling link.
rm -rf "$LINK_DIR"
mkdir -p "$LINK_DIR"

link() {  # $1 = skill dir relative to ~
  [ -f "$1/SKILL.md" ] || return 0
  ln -sfn "$HOME/$1" "$LINK_DIR/$(basename "$1")"
}

# Active optional skills first, then core skills (linked last so they win any name
# collision, as core is authoritative).
while IFS= read -r name || [ -n "$name" ]; do
  [ -n "$name" ] || continue
  link "$SKILLS_DIR/$name"
done < "$ACTIVE"

for d in "$CORE_SKILLS_DIR"/*/; do
  [ -d "$d" ] && link "${d%/}"
done

#!/usr/bin/env bash
# One owner for the sparse-checkout cone. The cone is derived, never hand-maintained:
#   - the skills on disk (the installed set; engine and uninstalled skills stay out)
#   - every other tracked top-level directory under agent/ (agents version their own
#     dirs there; a reapply must never prune them - issue #979)
#   - agent/core, only when an unmanaged box has already opted it in (SETUP.md)
# Usage: set-cone.sh [--add <skill-dir>] [--remove <skill-dir>]
# --add cones a not-yet-materialized skill in; --remove drops an installed one. Both
# recompute the rest of the cone, so they are also how skills-install/skills-remove
# pick up dirs committed since the last computation.
set -euo pipefail

ADD="" REMOVE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --add) ADD="$2"; shift 2 ;;
    --remove) REMOVE="$2"; shift 2 ;;
    *) echo "usage: set-cone.sh [--add <skill-dir>] [--remove <skill-dir>]" >&2; exit 2 ;;
  esac
done

cd ~

CONE="$(
  find agent/skills -mindepth 1 -maxdepth 1 -type d
  if [ -n "$ADD" ]; then printf '%s\n' "$ADD"; fi
  # No HEAD yet (fresh attach, before the first commit): nothing tracked, skills only.
  if git rev-parse -q --verify HEAD >/dev/null; then
    git ls-tree -d --name-only HEAD agent/ | grep -vxE 'agent/(core|skills)' || true
  fi
  git sparse-checkout list 2>/dev/null | grep -x 'agent/core' || true
)"
if [ -n "$REMOVE" ]; then
  CONE="$(printf '%s\n' "$CONE" | grep -vxF "$REMOVE" || true)"
fi
printf '%s\n' "$CONE" | sort -u | git sparse-checkout set --cone --stdin

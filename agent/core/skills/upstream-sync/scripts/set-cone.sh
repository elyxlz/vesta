#!/usr/bin/env bash
# One owner for the sparse-checkout cone. Entries are derived, never hand-maintained:
#   - installed skills: the current cone's agent/skills entries (the cone is the record
#     of what is installed - a removed skill whose dir git couldn't prune must not come
#     back; disk is only trusted on first attach, before a cone exists)
#   - every tracked directory at the workspace root and top-level under agent/ except
#     the engine (agents version their own dirs there; a reapply must never prune them -
#     issue #979)
#   - agent/core, only for an unmanaged box that opted in (SETUP.md): the entry must
#     already be in the cone AND core must be writable, so a stray entry on a managed
#     box (whose core is a read-only mount) heals itself on the next recompute
# Usage: set-cone.sh [--add <skill-dir> | --remove <skill-dir>]
# --add cones a not-yet-materialized skill in; --remove drops an installed one. Both
# recompute the rest of the cone, so they are also how skills-install/skills-remove
# pick up dirs committed since the last computation. Every cone update must go through
# here: a raw `git sparse-checkout set/add/reapply` computed elsewhere can still prune
# a dir committed after the last recompute.
set -euo pipefail

ADD="" REMOVE=""
case "${1:-}" in
  "") ;;
  --add) ADD="${2:?usage: set-cone.sh --add <skill-dir>}" ;;
  --remove) REMOVE="${2:?usage: set-cone.sh --remove <skill-dir>}" ;;
  *) echo "usage: set-cone.sh [--add <skill-dir> | --remove <skill-dir>]" >&2; exit 2 ;;
esac

cd ~

# Cone-mode workspaces only: rewriting a legacy no-cone sparse file here would
# force-convert it. The workspace boot migration owns that conversion.
if [ -f .git/info/sparse-checkout ] && [ "$(git config --get core.sparseCheckoutCone || true)" != "true" ]; then
  echo "legacy workspace: the workspace conversion (a boot migration) must run first" >&2
  exit 4
fi

CONE="$(
  if [ -f .git/info/sparse-checkout ]; then
    git sparse-checkout list | grep '^agent/skills/' || true
  else
    find agent/skills -mindepth 1 -maxdepth 1 -type d
  fi
  if [ -n "$ADD" ]; then printf '%s\n' "$ADD"; fi
  # Nothing tracked before the first commit on a fresh attach.
  if git rev-parse -q --verify HEAD >/dev/null; then
    git ls-tree -d --name-only HEAD agent/ | grep -vxE 'agent/(core|skills)' || true
    git ls-tree -d --name-only HEAD | grep -vx agent || true
  fi
  if [ -w agent/core ]; then
    git sparse-checkout list 2>/dev/null | grep -x 'agent/core' || true
  fi
)"
if [ -n "$REMOVE" ]; then
  CONE="$(printf '%s\n' "$CONE" | grep -vxF "$REMOVE" || true)"
fi
# An empty cone would prune every tracked file under agent/ (MEMORY.md included).
if [ -z "$CONE" ]; then
  echo "refusing to set an empty cone: no skills would remain and nothing tracked is kept" >&2
  exit 1
fi
printf '%s\n' "$CONE" | sort -u | git sparse-checkout set --cone --stdin

# Sparsifying agent/core means deleting the read-only mount, which git can't do, so it leaves
# the entry worktree-live and every later checkout rewrites the mount (#1280); pin it in the index.
if [ ! -w agent/core ]; then
  git ls-files -z -- agent/core | xargs -0r git update-index --skip-worktree --
fi

#!/usr/bin/env bash
# Re-anchor the agent branch onto upstream when the two share NO common ancestor.
#
# This happens when the upstream repo was recreated: previously-merged commits get
# new SHAs, so `git merge-base HEAD FETCH_HEAD` finds nothing and a normal merge is
# forced into `--allow-unrelated-histories`, flooding with false conflicts on every
# file that differs textually. Instead of grinding through them, take the upstream
# tree as the new base and replay only the files the agent owns on top.
#
# Owned files preserved across the re-anchor:
#   agent/MEMORY.md, agent/.gitignore, root .gitignore, agent/prompts/, and every
#   skill directory currently on disk under agent/skills/ (defaults + installed +
#   self-authored). Everything else (core, registry, code) comes from upstream.
#
# Run AFTER narrowing the sparse cone and dropping spillover, so only the skills you
# actually keep are on disk to be replayed. Fetch the upstream ref first:
#   git -C ~ fetch origin "$VESTA_UPSTREAM_REF"
#
# A docker snapshot is the safety net for the worktree; this script does not back up.
# It no-ops when a common ancestor already exists (a normal merge is correct there).
#
# Assumes $HOME is the repo root.

set -euo pipefail

REPO="${HOME}"
cd "$REPO"

if ! git rev-parse --verify -q FETCH_HEAD >/dev/null; then
  echo "error: no FETCH_HEAD. Run: git -C ~ fetch origin \"\$VESTA_UPSTREAM_REF\"" >&2
  exit 1
fi

if git merge-base HEAD FETCH_HEAD >/dev/null 2>&1; then
  echo "histories share a common ancestor; use a normal merge, not re-anchor."
  exit 0
fi

REF_DESC="$(git rev-parse --short FETCH_HEAD)"
SAVE="$(mktemp -d)"
trap 'rm -rf "$SAVE"' EXIT

# Collect the owned paths that currently exist, NUL-delimited.
{
  for p in agent/MEMORY.md agent/.gitignore .gitignore; do
    [ -f "$p" ] && printf '%s\0' "$p"
  done
  [ -d agent/prompts ] && printf '%s\0' agent/prompts
  if [ -d agent/skills ]; then
    find agent/skills -mindepth 1 -maxdepth 1 -type d -print0
  fi
} > "$SAVE/owned"

# Snapshot owned files (preserving paths) before we move the branch.
if [ -s "$SAVE/owned" ]; then
  tar -C "$REPO" --null -T "$SAVE/owned" -cf "$SAVE/owned.tar"
fi

# Take the upstream tree as the new base. skip-worktree / sparse paths (core etc.)
# update only in the index, not the worktree, so read-only bind mounts are untouched
# and a previously committed core divergence is dropped in favour of upstream's.
git reset --hard FETCH_HEAD

# Re-enforce the sparse cone so any upstream-only out-of-cone paths (new skills, core)
# stay off disk rather than being materialised by the reset.
if [ "$(git config --get core.sparseCheckout 2>/dev/null)" = "true" ]; then
  git sparse-checkout reapply
fi

# Replay the owned files on top.
[ -f "$SAVE/owned.tar" ] && tar -C "$REPO" -xf "$SAVE/owned.tar"
git add -A

if git diff --cached --quiet; then
  echo "re-anchored onto $REF_DESC; owned files match upstream, branch now equals upstream."
else
  git commit -m "chore: re-anchor onto $REF_DESC, replay agent-owned files" >/dev/null
  echo "re-anchored onto $REF_DESC; replayed agent-owned files."
fi

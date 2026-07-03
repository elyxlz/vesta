#!/usr/bin/env bash
# Attach $HOME to the published agent branch. Idempotent and worktree-safe: the only
# working-tree-touching step is `git reset --mixed`, which never writes files, so local
# content can never be clobbered - differences just show up in `git status` afterwards.
#
# Exit: 0 attached (or already attached); 3 snapshot tag for the running version not
# found on the remote; 4 legacy workspace detected (follow the migration flow in
# SKILL.md: back up, retire ~/.git, re-run).
set -euo pipefail

REF="${VESTA_UPSTREAM_REF:?VESTA_UPSTREAM_REF is unset (source /run/vestad-env)}"
NAME="${AGENT_NAME:?AGENT_NAME is unset (source /run/vestad-env)}"
URL="${VESTA_UPSTREAM_URL:-https://github.com/elyxlz/vesta.git}"
cd ~

VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"

if [ -d .git ]; then
  # Legacy shape: the pre-branch workspace used hand-built no-cone sparse patterns.
  if [ -f .git/info/sparse-checkout ] && grep -q '^!' .git/info/sparse-checkout 2>/dev/null; then
    echo "legacy workspace detected: follow the migration flow in SKILL.md" >&2
    exit 4
  fi
else
  git init -b "$NAME"
fi

git remote get-url origin >/dev/null 2>&1 || git remote add origin "$URL"
git remote set-url origin "$URL"
# Fetch exactly the agent branch + snapshot tags; never the monorepo's branches or
# release tags (those would drag master history onto the box).
git config remote.origin.tagOpt --no-tags
git config --unset-all remote.origin.fetch 2>/dev/null || true
git config remote.origin.fetch "+refs/heads/$REF:refs/remotes/origin/$REF"
git config --add remote.origin.fetch '+refs/tags/agent-v*:refs/tags/agent-v*'
git config user.name "$NAME"
git config user.email "$NAME@vesta"

git fetch origin
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || {
  echo "snapshot $TAG not found on $REF - was this release published?" >&2
  exit 3
}

# Cone = the skills on disk (installed set) - engine and uninstalled skills stay out.
find agent/skills -mindepth 1 -maxdepth 1 -type d | sort | git sparse-checkout set --cone --stdin

if ! git rev-parse -q --verify HEAD >/dev/null; then
  git update-ref "refs/heads/$NAME" "$TAG"
  git reset --mixed   # load index from the snapshot; worktree untouched
fi
echo "attached: branch $NAME on $TAG"

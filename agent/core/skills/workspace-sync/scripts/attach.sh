#!/usr/bin/env bash
# Attach $HOME to this vestad's workspace content. Idempotent and worktree-safe: the only
# working-tree-touching steps are `git reset --mixed` (never writes files) and materializing
# the root .gitignore when absent, so local content can never be clobbered - differences
# just show up in `git status` afterwards.
#
# Exit: 0 attached (or already attached); 3 snapshot tag for the running version not in
# the workspace bundle; 4 legacy workspace detected (the one-time workspace boot
# migration converts it: back up, retire ~/.git, re-run).
set -euo pipefail

NAME="${AGENT_NAME:?AGENT_NAME is unset (source /run/vestad-env)}"
cd ~

VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"

if [ -d .git ]; then
  # Legacy shape: the pre-branch workspace used hand-built no-cone sparse patterns.
  # Cone-mode files also carry '!' lines, so key on the cone config: an attached
  # workspace always has core.sparseCheckoutCone=true, a legacy one never does.
  if [ -f .git/info/sparse-checkout ] && [ "$(git config --get core.sparseCheckoutCone || true)" != "true" ] && grep -q '^!' .git/info/sparse-checkout 2>/dev/null; then
    echo "legacy workspace detected: the one-time workspace boot migration converts it" >&2
    exit 4
  fi
else
  git init -b "$NAME"
fi

git config user.name "$NAME"
git config user.email "$NAME@vesta"
# The read-only core mount provides out-of-cone files on disk; without this, git
# clears their skip-worktree bit (present = "user wants it back") and mount content
# starts leaking into status and add -A.
git config sparse.expectFilesOutsideOfPatterns true

bash ~/agent/core/skills/workspace-sync/scripts/fetch-workspace.sh
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || {
  echo "snapshot $TAG not in the workspace bundle - is vestad on a different version?" >&2
  exit 3
}

# Cone = the skills on disk (installed set) - engine and uninstalled skills stay out.
find agent/skills -mindepth 1 -maxdepth 1 -type d | sort | git sparse-checkout set --cone --stdin

if ! git rev-parse -q --verify HEAD >/dev/null; then
  git update-ref "refs/heads/$NAME" "$TAG"
  git reset --mixed   # load index from the snapshot; worktree untouched
fi
# The branch's root .gitignore (ignore everything but agent/) keeps $HOME noise out of
# git status. The image doesn't ship it; materialize it when absent - creating a file
# that doesn't exist clobbers nothing.
[ -f .gitignore ] || git checkout -- .gitignore 2>/dev/null || true
echo "attached: branch $NAME on $TAG"

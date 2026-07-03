#!/usr/bin/env bash
# Maintain this host's agent-workspace repo and bundle from the extracted agent content.
# Run by vestad at startup (after ensure_agent_code); also tested directly by
# agent/tests/test_build_workspace.py -- the same file in both places, so tests and
# production cannot drift.
#
# Usage: build-workspace.sh <content-dir> <workspace-dir> <version>
#   content-dir    the extracted agent home (core/, skills/, MEMORY.md, .gitignore)
#   workspace-dir  owns workspace.git (bare) and workspace.bundle
#   version        the running vesta version; tags the snapshot agent-v<version>
#
# Append-only per host: one snapshot commit per content change on branch agent-workspace,
# tag agent-v<version> force-set to the head (it only actually moves under dev churn --
# releases bump the version every time). The bundle, not the repo, is what boxes fetch.
set -euo pipefail

CONTENT="${1:?Usage: build-workspace.sh <content-dir> <workspace-dir> <version>}"
WS="${2:?workspace-dir required}"
VERSION="${3:?version required}"
BRANCH="agent-workspace"
TAG="agent-v$VERSION"
REPO="$WS/workspace.git"
BUNDLE="$WS/workspace.bundle"

mkdir -p "$WS"
[ -d "$REPO" ] || git init -q --bare -b "$BRANCH" "$REPO"

STAGE="$(mktemp -d)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

# Staged tree: agent/<content> (sans the extraction fingerprint) + the root scoping
# .gitignore (everything in $HOME but agent/ stays out of git status on a box).
mkdir -p "$STAGE/agent"
cp -a "$CONTENT/." "$STAGE/agent/"
rm -f "$STAGE/agent/.vestad-fingerprint"
cat > "$STAGE/.gitignore" <<'EOF'
/*
!/.gitignore
!/agent/
EOF

export GIT_DIR="$REPO" GIT_WORK_TREE="$STAGE" GIT_INDEX_FILE="$STAGE/.build-index"
export GIT_AUTHOR_NAME="vesta" GIT_AUTHOR_EMAIL="vesta@vesta"
export GIT_COMMITTER_NAME="vesta" GIT_COMMITTER_EMAIL="vesta@vesta"
# Hermetic against the host's git config: a user-level tag.gpgSign/commit.gpgSign (or any
# other global setting) must not break or alter vestad's snapshot construction.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

git add -A
TREE="$(git write-tree)"
PARENT="$(git rev-parse -q --verify "refs/heads/$BRANCH" || true)"

if [ -n "$PARENT" ] && [ "$(git rev-parse "$PARENT^{tree}")" = "$TREE" ] \
   && [ "$(git rev-parse -q --verify "refs/tags/$TAG^{commit}" || true)" = "$PARENT" ] \
   && [ -f "$BUNDLE" ]; then
  echo "workspace: no content change for v$VERSION; nothing to do"
  exit 0
fi

if [ -z "$PARENT" ] || [ "$(git rev-parse "$PARENT^{tree}")" != "$TREE" ]; then
  COMMIT="$(git commit-tree "$TREE" ${PARENT:+-p "$PARENT"} -m "snapshot v$VERSION")"
  git update-ref "refs/heads/$BRANCH" "$COMMIT"
fi
git tag -f "$TAG" "refs/heads/$BRANCH" >/dev/null

# Regenerate atomically: boxes may be mid-download of the old bundle; rename is safe.
TAG_REFS="$(git tag -l 'agent-v*' | sed 's|^|refs/tags/|')"
# shellcheck disable=SC2086
git bundle create "$BUNDLE.tmp" "refs/heads/$BRANCH" $TAG_REFS 2>/dev/null
mv "$BUNDLE.tmp" "$BUNDLE"
echo "workspace: $BRANCH at $TAG ($(git rev-parse --short "refs/heads/$BRANCH"))"

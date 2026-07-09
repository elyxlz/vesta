#!/usr/bin/env bash
# Maintain this host's upstream repo and bundle from the extracted agent content.
# Run by vestad at startup (after ensure_agent_code); also tested directly by
# agent/tests/test_build_upstream.py -- the same file in both places, so tests and
# production cannot drift.
#
# Usage: build-upstream.sh <content-dir> <upstream-dir> <version>
#   content-dir    the extracted agent home (core/, skills/, MEMORY.md, .gitignore)
#   upstream-dir   owns upstream.git (bare) and workspace.bundle
#   version        the running vesta version; tags the snapshot agent-v<version>
#
# Append-only per host: one snapshot commit per content change on branch agent-upstream,
# tag agent-v<version> force-set to the head (it only actually moves under dev churn --
# releases bump the version every time). Boxes fetch straight from the bind-mounted repo;
# the bundle is only still generated for pre-rename boxes (see LEGACY below).
set -euo pipefail

CONTENT="${1:?Usage: build-upstream.sh <content-dir> <upstream-dir> <version>}"
WS="${2:?upstream-dir required}"
VERSION="${3:?version required}"
BRANCH="agent-upstream"
# LEGACY(remove-when: no agent predating the release that ships this rename remains and
# the 2026-07 workspace migrations are fleet-applied): old boxes' checked-out
# fetch-workspace.sh fetches refs/heads/agent-workspace; publish it alongside.
LEGACY_BRANCH="agent-workspace"
TAG="agent-v$VERSION"
REPO="$WS/upstream.git"
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

# LEGACY(remove-when: same condition as LEGACY_BRANCH): a repo carried over from the
# workspace era has only agent-workspace; seed agent-upstream from it so the first
# post-rename snapshot extends that history instead of starting an orphan root.
if ! git rev-parse -q --verify "refs/heads/$BRANCH" >/dev/null \
   && git rev-parse -q --verify "refs/heads/$LEGACY_BRANCH" >/dev/null; then
  git update-ref "refs/heads/$BRANCH" "refs/heads/$LEGACY_BRANCH"
fi

git add -A
TREE="$(git write-tree)"
PARENT="$(git rev-parse -q --verify "refs/heads/$BRANCH" || true)"

if [ -n "$PARENT" ] && [ "$(git rev-parse "$PARENT^{tree}")" = "$TREE" ] \
   && [ "$(git rev-parse -q --verify "refs/tags/$TAG^{commit}" || true)" = "$PARENT" ] \
   && [ "$(git rev-parse -q --verify "refs/heads/$LEGACY_BRANCH" || true)" = "$PARENT" ] \
   && [ -f "$BUNDLE" ]; then
  echo "upstream: no content change for v$VERSION; nothing to do"
  exit 0
fi

if [ -z "$PARENT" ] || [ "$(git rev-parse "$PARENT^{tree}")" != "$TREE" ]; then
  COMMIT="$(git commit-tree "$TREE" ${PARENT:+-p "$PARENT"} -m "snapshot v$VERSION")"
  git update-ref "refs/heads/$BRANCH" "$COMMIT"
fi
git tag -f "$TAG" "refs/heads/$BRANCH" >/dev/null
git update-ref "refs/heads/$LEGACY_BRANCH" "refs/heads/$BRANCH"

# Regenerate atomically: boxes may be mid-download of the old bundle; rename is safe.
TAG_REFS="$(git tag -l 'agent-v*' | sed 's|^|refs/tags/|')"
# shellcheck disable=SC2086
git bundle create "$BUNDLE.tmp" "refs/heads/$BRANCH" "refs/heads/$LEGACY_BRANCH" $TAG_REFS 2>/dev/null
mv "$BUNDLE.tmp" "$BUNDLE"
echo "upstream: $BRANCH at $TAG ($(git rev-parse --short "refs/heads/$BRANCH"))"

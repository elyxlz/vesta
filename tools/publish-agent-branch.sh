#!/usr/bin/env bash
# Publish the complete agent home to the fleet branch: one commit + one agent-v<version>
# tag per release, append-only by construction (worktree rebuilt from the source ref and
# committed on top of the existing branch head — history is never rewritten, pushes are
# plain fast-forwards and the branch + tag land atomically or not at all).
#
# Usage: publish-agent-branch.sh <source-ref> [branch]
#   source-ref  commit to publish from (e.g. the release tag)
#   branch      target branch (default: agent-workspace; dev flows publish
#               agent-workspace-<branch>)
#
# Published tree: agent/core (engine incl. pyproject/uv.lock), agent/skills,
# agent/MEMORY.md, agent/.gitignore, plus a script-owned root .gitignore. Nothing else —
# never .claude, never the rest of the monorepo, never dev-tool configs.
set -euo pipefail

SRC_REF="${1:?Usage: publish-agent-branch.sh <source-ref> [branch]}"
BRANCH="${2:-agent-workspace}"
REMOTE="origin"
PUBLISH_PATHS=(agent/core agent/skills agent/MEMORY.md agent/.gitignore)

VERSION="$(git show "$SRC_REF:agent/core/pyproject.toml" | grep '^version = ' | cut -d'"' -f2)"
[ -n "$VERSION" ] || { echo "error: could not read version from $SRC_REF" >&2; exit 1; }
TAG="agent-v$VERSION"
SRC_SHA="$(git rev-parse "$SRC_REF")"

WORK="$(mktemp -d)"
STAGE="$(mktemp -d)"
cleanup() { git worktree remove --force "$WORK" 2>/dev/null || true; rm -rf "$WORK" "$STAGE"; }
trap cleanup EXIT

git archive "$SRC_REF" "${PUBLISH_PATHS[@]}" | tar -x -C "$STAGE"
cat > "$STAGE/.gitignore" <<'EOF'
/*
!/.gitignore
!/agent/
*.bin
*.onnx
*.pt
*.db
*.sqlite
*.mp3
*.mp4
*.wav
*.zip
*.tar.gz
node_modules/
dist/
.venv/
__pycache__/
EOF

if git fetch "$REMOTE" "$BRANCH" 2>/dev/null; then
  # FETCH_HEAD is per-worktree: resolve it here, before entering the linked worktree.
  BASE_SHA="$(git rev-parse FETCH_HEAD)"
  # Append-only guard: every published snapshot must still be reachable from the branch.
  # A missing one means the remote branch was rewritten behind our back — building on top
  # would silently bless the rewrite, so fail loudly instead.
  for published_tag in $(git tag -l 'agent-v*'); do
    if ! git merge-base --is-ancestor "$published_tag" "$BASE_SHA"; then
      echo "error: remote $BRANCH no longer contains published snapshot $published_tag (history rewritten?)" >&2
      exit 1
    fi
  done
  git worktree add "$WORK" "$BASE_SHA"
  git -C "$WORK" checkout -B "$BRANCH" "$BASE_SHA"
else
  git worktree add --detach "$WORK"
  git -C "$WORK" checkout --orphan "$BRANCH"
  git -C "$WORK" rm -rfq --cached . 2>/dev/null || true
  find "$WORK" -mindepth 1 -maxdepth 1 -not -name .git -exec rm -rf {} +
fi

# --ignore-times: the staged tree carries git-archive mtimes (the source commit's
# timestamp), which can equal the fresh checkout's mtime to the second while sizes
# match (e.g. only a version string changed) — rsync's quick-check would silently
# skip those files and publish a stale tree.
rsync -a --ignore-times --delete --exclude=.git "$STAGE/" "$WORK/"
git -C "$WORK" add -A
if git -C "$WORK" diff --cached --quiet 2>/dev/null && git -C "$WORK" rev-parse -q --verify HEAD >/dev/null; then
  echo "publish: no content change for v$VERSION; nothing to do"
  exit 0
fi
git -C "$WORK" commit -m "publish v$VERSION from ${SRC_SHA:0:12}"
git -C "$WORK" tag "$TAG"
# Plain push: fast-forward-only by git's default; --atomic lands branch+tag together or not at all.
git -C "$WORK" push --atomic "$REMOTE" "refs/heads/$BRANCH:refs/heads/$BRANCH" "refs/tags/$TAG:refs/tags/$TAG"
echo "publish: $BRANCH -> v$VERSION ($TAG)"

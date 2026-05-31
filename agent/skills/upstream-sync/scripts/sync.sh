#!/usr/bin/env bash
# Pull upstream into the agent's branch, deterministically.
#
# Runs the whole mechanical spine so the agent never hand-types git:
#   checkpoint -> narrow cone -> fetch -> (merge if shared history, else re-anchor)
#   -> force skills/index.json to the upstream registry -> re-apply skip-worktree
#   -> print divergence.
#
# The ONLY thing left to the agent is resolving real content conflicts. If a merge
# conflicts, sync stops with exit code 2 and lists the files. Resolve each (edit,
# then `git -C ~ add <file>`) and run sync.sh again; it finalises and finishes.
#
# Exit codes: 0 = synced / up to date, 2 = conflicts to resolve, 1 = error.
# Assumes $HOME is the repo root and $VESTA_UPSTREAM_REF names the upstream ref.

set -euo pipefail

REPO="${HOME}"
cd "$REPO"
HERE="$(cd "$(dirname "$0")" && pwd)"
REF="${VESTA_UPSTREAM_REF:?VESTA_UPSTREAM_REF is unset}"
INDEX="agent/skills/index.json"

say() { printf '\n== %s\n' "$1"; }

# index.json is the upstream registry of ALL available skills (skills-install reads
# it); the agent never edits it. Always take the incoming version so a sparse merge
# can never shrink or corrupt it. $1 is the source ref (MERGE_HEAD or FETCH_HEAD).
take_upstream_index() {
  git cat-file -e "$1:$INDEX" 2>/dev/null || return 0
  git checkout "$1" -- "$INDEX" 2>/dev/null || true
}

summary() {
  if git merge-base HEAD FETCH_HEAD >/dev/null 2>&1; then
    printf '  behind upstream: %s   local commits ahead: %s\n' \
      "$(git rev-list --count HEAD..FETCH_HEAD)" "$(git rev-list --count FETCH_HEAD..HEAD)"
  fi
  local changed
  changed="$(git diff --stat FETCH_HEAD...HEAD -- agent/ ":(exclude)$INDEX" 2>/dev/null | tail -1)"
  if [ -n "$changed" ]; then printf '  your changes vs upstream:%s\n' "$changed"; else printf '  no committed divergence from upstream.\n'; fi
}

finalize() {
  take_upstream_index FETCH_HEAD
  if ! git diff --cached --quiet -- "$INDEX" 2>/dev/null; then
    git commit -q -m "chore: sync skills/index.json to upstream registry"
  fi
  # Re-apply skip-worktree on bind-mounted paths (merge re-stats and clears it).
  if mount 2>/dev/null | grep -q '/root/agent/core '; then
    git ls-files agent/core agent/pyproject.toml agent/uv.lock 2>/dev/null | xargs -r git update-index --skip-worktree
  fi
  say "Done. Divergence from $REF:"
  summary
}

# Finalise a merge in progress (clean staged, or freshly conflicted): take upstream's
# index, then either stop on remaining conflicts or commit and finalise.
complete_merge() {
  take_upstream_index MERGE_HEAD
  if git ls-files -u | grep -q .; then
    say "Merge conflicts to resolve:"
    git diff --name-only --diff-filter=U | sed 's/^/  /'
    printf '\nResolve each (edit, then: git -C ~ add <file>), then run sync.sh again to finish.\n'
    exit 2
  fi
  git commit -q --no-edit
  finalize
  exit 0
}

# --- Phase A: a previous run left a merge in progress ---
if git rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1; then
  complete_merge
fi

# --- Phase B: fresh sync ---
say "Checkpoint local work"
git add agent/ --ignore-errors
git diff --cached --name-only --diff-filter=D | grep -v '^agent/' | xargs -r git reset -q HEAD -- 2>/dev/null || true
if ! git diff --cached --quiet; then
  git commit -q -m "chore: checkpoint before sync to $REF"
fi
# Bind-mount drift: an image rebuild can clear skip-worktree on these, which would
# abort the merge with "local changes would be overwritten". Baseline them first.
if ! git diff --quiet -- agent/pyproject.toml agent/uv.lock 2>/dev/null; then
  git update-index --no-skip-worktree agent/pyproject.toml agent/uv.lock 2>/dev/null || true
  git add --sparse agent/pyproject.toml agent/uv.lock 2>/dev/null || true
  git commit -q -m "chore: baseline bind-mount state" 2>/dev/null || true
fi

say "Narrow sparse cone"
"$HERE/narrow-sparse-checkout.sh"

say "Fetch $REF"
git fetch -q origin "$REF"

if [ "$(git rev-parse HEAD)" = "$(git rev-parse FETCH_HEAD)" ]; then
  say "Already up to date with $REF"
  summary
  exit 0
fi

if git merge-base HEAD FETCH_HEAD >/dev/null 2>&1; then
  say "Merge $REF"
  if git merge FETCH_HEAD --no-edit; then
    finalize
    exit 0
  fi
  complete_merge
else
  say "No shared history with upstream; re-anchoring"
  "$HERE/reanchor.sh"
  finalize
  exit 0
fi

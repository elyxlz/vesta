#!/usr/bin/env bash
# Pull upstream into the agent's branch, deterministically.
#
# Spine: checkpoint -> stop tracking vestad-managed paths -> narrow cone -> fetch
#   -> merge a core-less copy of upstream -> force skills/index.json to the registry
#   -> print divergence.
#
# agent/core, pyproject.toml and uv.lock are vestad-managed read-only bind mounts. The
# agent never edits, tracks or contributes them, so they are stripped from the merge and
# gitignored: git never touches the read-only mount, and a merge only ever surfaces REAL
# conflicts on files the agent actually owns.
#
# The only thing left to the agent is resolving those real conflicts: on conflict sync
# exits 2 and lists the files; resolve each (edit, then `git -C ~ add <file>`) and run
# sync.sh again to finish.
#
# Exit codes: 0 = synced / up to date, 2 = conflicts to resolve, 1 = error.
# Assumes $HOME is the repo root and $VESTA_UPSTREAM_REF names the upstream ref.

set -euo pipefail

REPO="${HOME}"
cd "$REPO"
HERE="$(cd "$(dirname "$0")" && pwd)"
REF="${VESTA_UPSTREAM_REF:?VESTA_UPSTREAM_REF is unset}"
INDEX="agent/skills/index.json"
MANAGED="agent/core agent/pyproject.toml agent/uv.lock"

say() { printf '\n== %s\n' "$1"; }

# index.json is the upstream registry of ALL available skills (skills-install reads it);
# the agent never edits it. Always take the incoming version so a merge can't shrink or
# corrupt it. $1 is the source ref (MERGE_HEAD or FETCH_HEAD).
take_upstream_index() {
  git cat-file -e "$1:$INDEX" 2>/dev/null || return 0
  git checkout "$1" -- "$INDEX" 2>/dev/null || true
}

# Echo a copy of commit $1 with the vestad-managed paths stripped, so merging it never
# tracks or writes agent/core et al.
coreless() {
  local idx tree
  idx="$(mktemp)"
  GIT_INDEX_FILE="$idx" git read-tree "$1"
  GIT_INDEX_FILE="$idx" git -c core.sparseCheckout=false rm -rf --cached --quiet --ignore-unmatch $MANAGED >/dev/null 2>&1 || true
  tree="$(GIT_INDEX_FILE="$idx" git write-tree)"
  rm -f "$idx"
  git commit-tree "$tree" -p "$1" -m "coreless $REF"
}

untrack_managed() {
  git ls-files -- $MANAGED | xargs -r git update-index --force-remove
}

ensure_gitignored() {
  local gi="agent/.gitignore" line
  [ -f "$gi" ] || : > "$gi"
  while IFS= read -r line; do
    [ -n "$line" ] && { grep -qFx "$line" "$gi" || printf '%s\n' "$line" >> "$gi"; }
  done < "$HERE/../managed.gitignore"
  git add --sparse "$gi" 2>/dev/null || true
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
  say "Done. Divergence from $REF:"
  summary
}

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
# Stop tracking vestad-managed paths (they come from the read-only mount, never via git) and
# gitignore them BEFORE the first `git add`. On a fresh `git init` agent they are present on
# disk, untracked and outside the sparse cone; staging them before they are ignored makes
# `git add` exit 1 and (under set -e) aborts the very first sync. Idempotent.
untrack_managed
ensure_gitignored

say "Checkpoint local work"
git add agent/ --ignore-errors
git diff --cached --name-only --diff-filter=D | grep -v '^agent/' | xargs -r git reset -q HEAD -- 2>/dev/null || true
if ! git diff --cached --quiet; then
  git commit -q -m "chore: checkpoint before sync to $REF"
fi

say "Narrow sparse cone"
"$HERE/narrow-sparse-checkout.sh"

say "Fetch $REF"
git fetch -q origin "$REF"

if git rev-parse -q --verify HEAD >/dev/null 2>&1 && git merge-base --is-ancestor FETCH_HEAD HEAD 2>/dev/null; then
  say "Already up to date with $REF"
  summary
  exit 0
fi

CL="$(coreless FETCH_HEAD)"
flags=""
git merge-base HEAD "$CL" >/dev/null 2>&1 || flags="--allow-unrelated-histories"
if [ -n "$flags" ]; then
  say "Merge $REF (no shared history: real conflicts on changed files will surface)"
else
  say "Merge $REF"
fi
if git merge "$CL" --no-edit $flags; then
  finalize
  exit 0
fi
complete_merge

#!/usr/bin/env bash
# Scaffold or tear down per-area worktrees for a parallel LOC-reduction pass.
#
#   worktrees.sh setup    <repo-root> <area>...   # base branch + one worktree per area
#   worktrees.sh teardown <repo-root> <area>...   # remove them again
#
# Worktrees are created as siblings of <repo-root> (../wt-rl-<area>) on branches
# reduce-loc/<area>, all forked from a base branch refactor/reduce-loc tracking origin/master.
set -euo pipefail

BASE_BRANCH="refactor/reduce-loc"

cmd="${1:?usage: worktrees.sh setup|teardown <repo-root> <area>...}"
root="${2:?missing <repo-root>}"
shift 2
[ "$#" -gt 0 ] || { echo "give at least one <area>" >&2; exit 1; }

parent="$(cd "$root/.." && pwd)"
git -C "$root" fetch origin master -q

case "$cmd" in
  setup)
    git -C "$root" worktree add -b "$BASE_BRANCH" "$parent/wt-reduce" origin/master
    for area in "$@"; do
      git -C "$root" worktree add -b "reduce-loc/$area" "$parent/wt-rl-$area" "$BASE_BRANCH"
      echo "ready: $parent/wt-rl-$area  (branch reduce-loc/$area)"
    done
    ;;
  teardown)
    for area in "$@"; do
      git -C "$root" worktree remove --force "$parent/wt-rl-$area" 2>/dev/null || true
      git -C "$root" branch -D "reduce-loc/$area" 2>/dev/null || true
    done
    git -C "$root" worktree remove --force "$parent/wt-reduce" 2>/dev/null || true
    git -C "$root" worktree prune
    ;;
  *) echo "unknown command: $cmd" >&2; exit 1 ;;
esac

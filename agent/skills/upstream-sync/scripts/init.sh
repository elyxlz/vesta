#!/usr/bin/env bash
# First-time git setup for upstream sync: init the repo, pin the sparse-checkout cone to
# the skills currently on disk, and create the agent's branch. Idempotent, safe to re-run.
# The ongoing pull flow is sync.sh; this runs once at first wake.
#
# Why a script and not inline bash in SETUP.md: the cone is built from `find -printf` rather
# than a shell glob, so the patterns are always repo-relative no matter the caller's cwd. An
# earlier inline version expanded `~/agent/skills/*/` to absolute paths and wrote dead
# `//root/agent/skills/...` patterns, which dropped every skill out of the cone and made the
# first sync abort. Assumes $HOME is the repo root; $AGENT_NAME comes from /run/vestad-env.

set -euo pipefail

REPO="${HOME}"
REMOTE="https://github.com/elyxlz/vesta.git"
: "${AGENT_NAME:?AGENT_NAME is unset (source /run/vestad-env first)}"

cd "$REPO"

[ -d .git ] || git init -q
git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REMOTE"
git sparse-checkout init --no-cone

# agent/skills/*/ is opt-in: re-include only the skill dirs already on disk (the image
# defaults). New upstream skills land in agent/skills/index.json (the registry) but stay off
# disk until skills-install adds them.
{
  printf '%s\n' '/agent/' '!/agent/core/' '!/agent/pyproject.toml' '!/agent/uv.lock' '!/agent/skills/*/' '/.gitignore'
  find agent/skills -mindepth 1 -maxdepth 1 -type d -printf '/agent/skills/%f/\n' 2>/dev/null | sort
} > .git/info/sparse-checkout

git config user.name "$AGENT_NAME"
git config user.email "$AGENT_NAME@vesta"
git rev-parse --verify "$AGENT_NAME" >/dev/null 2>&1 || git checkout -q -b "$AGENT_NAME"

echo "init: repo ready on branch $AGENT_NAME; sparse cone pinned to:"
find agent/skills -mindepth 1 -maxdepth 1 -type d -printf '  %f\n' 2>/dev/null | sort

#!/usr/bin/env bash
# Attach $HOME to this vestad's upstream content: a plain full checkout of the
# agent-upstream snapshot (skills + MEMORY.md; core is a read-only mount, gitignored).
# Idempotent and non-clobbering - a re-attach only fetches, it never overwrites local
# edits. Exit: 0 attached; 3 snapshot tag for the running version not in the upstream
# repo; 4 legacy sparse-cone workspace (the flat-checkout boot migration converts it).
set -euo pipefail

NAME="${AGENT_NAME:?AGENT_NAME is unset (source /run/vestad-env)}"
cd ~

VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"

if [ -d .git ]; then
  # Old shape: a sparse-checkout workspace. The flat-checkout boot migration converts it;
  # attach refuses to touch it so it can never half-convert.
  if [ -f .git/info/sparse-checkout ] || [ "$(git config --get core.sparseCheckout || true)" = "true" ]; then
    echo "legacy sparse workspace detected: the flat-checkout boot migration converts it" >&2
    exit 4
  fi
else
  git init -b "$NAME" >/dev/null
fi

git config user.name "$NAME"
git config user.email "$NAME@vesta"

bash ~/agent/core/skills/upstream-sync/scripts/fetch-upstream.sh
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || {
  echo "snapshot $TAG not in the upstream repo - is vestad on a different version?" >&2
  exit 3
}

if ! git rev-parse -q --verify HEAD >/dev/null; then
  # Virgin box: point the branch at the snapshot and materialize any tracked file the
  # image didn't bake in (notably the root .gitignore that scopes $HOME). The image's
  # skills and MEMORY.md are identical to the snapshot, so present files are left as-is.
  git update-ref "refs/heads/$NAME" "$TAG"
  git reset --mixed >/dev/null
  git ls-files -z | while IFS= read -r -d '' f; do [ -e "$f" ] || git checkout-index -f -- "$f"; done
fi
echo "attached: branch $NAME on $TAG"

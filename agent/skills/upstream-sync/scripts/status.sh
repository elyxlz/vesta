#!/usr/bin/env bash
# Show, concisely, how the agent's branch diverges from upstream. Read-only: it
# fetches and prints, changes nothing. Use it to decide what to integrate from
# upstream and what to contribute back (see upstream-pr).
#
# Assumes $HOME is the repo root and $VESTA_UPSTREAM_REF names the upstream ref.

set -euo pipefail

REPO="${HOME}"
cd "$REPO"
REF="${VESTA_UPSTREAM_REF:?VESTA_UPSTREAM_REF is unset}"
INDEX="agent/skills/index.json"

git fetch -q origin "$REF"
echo "upstream: $REF"

if git merge-base HEAD FETCH_HEAD >/dev/null 2>&1; then
  echo "behind: $(git rev-list --count HEAD..FETCH_HEAD) commit(s)   ahead: $(git rev-list --count FETCH_HEAD..HEAD) commit(s)"

  incoming="$(git log --oneline HEAD..FETCH_HEAD)"
  if [ -n "$incoming" ]; then
    printf '\nincoming from upstream (to integrate):\n'
    echo "$incoming" | sed 's/^/  /'
  fi

  # Three-dot: only what you changed since the common base, not unpulled upstream.
  yourdiff="$(git diff --stat "FETCH_HEAD...HEAD" -- agent/ ":(exclude)$INDEX")"
else
  echo "no shared history with upstream (next sync will re-anchor)"
  yourdiff="$(git diff --stat FETCH_HEAD -- agent/ ":(exclude)$INDEX")"
fi

printf '\nyour changes vs upstream (agent/, excluding generated index):\n'
if [ -n "$yourdiff" ]; then echo "$yourdiff" | sed 's/^/  /'; else echo "  (none)"; fi

uncommitted="$(git status --short)"
if [ -n "$uncommitted" ]; then
  printf '\nuncommitted:\n'
  echo "$uncommitted" | sed 's/^/  /'
fi

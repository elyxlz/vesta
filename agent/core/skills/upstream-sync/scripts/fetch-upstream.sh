#!/usr/bin/env bash
# Bring this box's upstream refs up to date from vestad's snapshot repo, bind-mounted
# read-only at /run/vesta-upstream -- no network, no auth, works even when vestad's API
# is down. VESTA_UPSTREAM_SOURCE overrides the source with any git-fetchable path
# (a bare repo or a bundle file; tests use both).
set -euo pipefail
cd ~

MOUNTED_REPO="/run/vesta-upstream/upstream.git"
SOURCE="${VESTA_UPSTREAM_SOURCE:-$MOUNTED_REPO}"

if [ "$SOURCE" = "$MOUNTED_REPO" ] && [ ! -d "$MOUNTED_REPO" ]; then
  # LEGACY(remove-when: no agent predating the release that ships this rename remains and
  # the 2026-07 workspace migrations are fleet-applied): a pre-rename container whose
  # rebuild was deferred (disk-full reconcile, failed rebuild) boots with the new core
  # but without the mount; fall back to the bundle endpoint the old script used so the
  # sync boot turn still lands on the first try.
  PORT="${VESTAD_PORT:?VESTAD_PORT is unset (source /run/vestad-env)}"
  NAME="${AGENT_NAME:?AGENT_NAME is unset (source /run/vestad-env)}"
  TOKEN="${AGENT_TOKEN:?AGENT_TOKEN is unset (source /run/vestad-env)}"
  SOURCE="$(mktemp)"
  trap 'rm -f "$SOURCE"' EXIT
  # -k: vestad's cert is self-signed; loopback only (same trust model as vestad_client.py).
  curl -fsSk -H "X-Agent-Token: $TOKEN" "https://localhost:$PORT/agents/$NAME/workspace.bundle" -o "$SOURCE"
fi

# The mounted repo is owned by the host user while the box runs as root, and git
# refuses to read a repo owned by another uid unless it is marked safe. Only global
# (or system) config satisfies the check -- command-scope `-c` is deliberately
# ignored for safe.directory -- so mark it once, idempotently.
if [ "$SOURCE" = "$MOUNTED_REPO" ]; then
  (git config --global --get-all safe.directory 2>/dev/null || true) | grep -qxF "$MOUNTED_REPO" \
    || git config --global --add safe.directory "$MOUNTED_REPO"
fi

git fetch --no-tags "$SOURCE" \
  '+refs/heads/agent-upstream:refs/remotes/upstream/agent-upstream' \
  '+refs/tags/agent-v*:refs/tags/agent-v*'

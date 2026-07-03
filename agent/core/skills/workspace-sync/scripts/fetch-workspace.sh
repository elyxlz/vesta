#!/usr/bin/env bash
# Bring this box's workspace refs up to date from vestad's bundle. The "remote" is
# whatever bundle this box's vestad serves -- no configured URL, no external network.
# VESTA_WORKSPACE_BUNDLE overrides with a local bundle path (tests).
set -euo pipefail
cd ~

BUNDLE="${VESTA_WORKSPACE_BUNDLE:-}"
TMP=""
if [ -z "$BUNDLE" ]; then
  PORT="${VESTAD_PORT:?VESTAD_PORT is unset (source /run/vestad-env)}"
  NAME="${AGENT_NAME:?AGENT_NAME is unset (source /run/vestad-env)}"
  TOKEN="${AGENT_TOKEN:?AGENT_TOKEN is unset (source /run/vestad-env)}"
  TMP="$(mktemp)"
  trap 'rm -f "$TMP"' EXIT
  # -k: vestad's cert is self-signed; loopback only (same trust model as vestad_client.py).
  curl -fsSk -H "X-Agent-Token: $TOKEN" "https://localhost:$PORT/agents/$NAME/workspace.bundle" -o "$TMP"
  BUNDLE="$TMP"
fi

git fetch --no-tags "$BUNDLE" \
  '+refs/heads/agent-workspace:refs/remotes/origin/agent-workspace' \
  '+refs/tags/agent-v*:refs/tags/agent-v*'

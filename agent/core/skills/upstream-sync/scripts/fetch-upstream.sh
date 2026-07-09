#!/usr/bin/env bash
# Bring this box's upstream refs up to date from vestad's snapshot repo, bind-mounted
# read-only at /run/vesta-upstream -- no network, no auth, works even when vestad's API
# is down. VESTA_UPSTREAM_SOURCE overrides the source with any git-fetchable path
# (a bare repo or a bundle file; tests use both).
set -euo pipefail
cd ~

SOURCE="${VESTA_UPSTREAM_SOURCE:-/run/vesta-upstream/upstream.git}"
git fetch --no-tags "$SOURCE" \
  '+refs/heads/agent-upstream:refs/remotes/upstream/agent-upstream' \
  '+refs/tags/agent-v*:refs/tags/agent-v*'

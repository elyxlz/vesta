#!/usr/bin/env bash
# Installs the two browser engines the browser daemon drives: Debian's chromium and the pinned
# Camoufox bundle. Run by the Dockerfile for fresh images and by the browser-daemon migration on
# the fleet (fleet upgrades never rerun the Dockerfile). Safe to rerun.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v chromium >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends chromium
  rm -rf /var/lib/apt/lists/*
fi

python3 "$SKILL_DIR/cli/src/vesta_browser/camoufox_install.py"

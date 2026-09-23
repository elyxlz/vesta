#!/usr/bin/env bash
# Put the pinned Claude Code CLI on PATH. The pin is the sibling `claude-code-version` file. The
# image build and every agent boot run this same script, so a `claude` that predates the pin is
# replaced on the next boot and one already at the pin costs a single version check.
set -euo pipefail

version="$(tr -d '[:space:]' < "$(dirname "$0")/claude-code-version")"
current="$(claude --version 2>/dev/null || true)"

if [[ "$current" == *"$version"* ]]; then
    exit 0
fi

curl -fsSL https://claude.ai/install.sh | bash -s "$version"
claude --version | grep -F "$version"

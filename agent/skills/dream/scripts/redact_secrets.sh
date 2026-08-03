#!/bin/sh
# Scan events DB for secrets; scrub the real leaks in place. Usage: redact_secrets.sh [--scrub ID ...]
#
# `uv run` picks its interpreter from the project it finds by walking up from the CURRENT
# working directory, not from the script's location. Called by absolute path from outside the
# agent tree (which is how the dream skill invokes it, and $HOME is outside), uv finds no
# project and falls back to a standalone Python that is older than the syntax this script uses,
# so it dies with a SyntaxError that looks like a broken script rather than a wrong interpreter.
# cd to the script's own directory first so the agent project is always the one resolved.
cd "$(dirname "$0")" || exit 1
exec uv run python3 ./redact_secrets.py "$@"

#!/bin/sh
# Scan events DB for secrets; scrub the real leaks in place. Usage: redact_secrets.sh [--scrub ID ...]
#
# `uv run` resolves its interpreter by walking up from the CURRENT working directory, not from
# the script's location, and what it finds by walking up from here is the engine venv at
# ~/agent/.venv. Invoked by absolute path from outside that tree (which is how the dream skill
# calls it, and $HOME is outside), it finds nothing and falls back to a standalone Python older
# than this script's syntax, dying with a SyntaxError that reads as a broken script.
cd "$(dirname "$0")" || exit 1
exec uv run python3 ./redact_secrets.py "$@"

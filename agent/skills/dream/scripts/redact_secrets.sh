#!/bin/sh
# Scan events DB for secrets; scrub the real leaks in place.
# Usage: redact_secrets.sh [--scrub ID ...] | redact_secrets.sh --scrub-literal 'VALUE'
#
# `uv run` resolves its interpreter by walking up from the CURRENT working directory, and the dream
# flow invokes this by absolute path from $HOME, where that walk finds a standalone Python too old
# for this script instead of the engine venv. cd to the script's own tree first so resolution is
# identical wherever the caller sits.
cd "$(dirname "$0")" || exit 1
exec uv run python3 ./redact_secrets.py "$@"

#!/bin/sh
# Scan events DB for secrets; scrub the real leaks in place. Usage: redact_secrets.sh [--scrub ID ...]
exec uv run python3 "$(dirname "$0")/redact_secrets.py" "$@"

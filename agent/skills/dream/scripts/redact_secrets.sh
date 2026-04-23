#!/bin/sh
# Scan events DB for secrets. Usage: redact_secrets.sh [--delete]
exec uv run python3 "$(dirname "$0")/redact_secrets.py" "$@"

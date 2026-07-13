#!/bin/sh
# Scan events DB for secrets and scrub known-leaked literals. Usage: redact_secrets.sh
exec uv run python3 "$(dirname "$0")/redact_secrets.py"

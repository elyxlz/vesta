#!/bin/bash
# Pull a redacted slice of a live Vesta agent's Claude session transcript (thinking +
# tool calls + tool RESULTS) for a retrospective. Runs the extractor inside the
# container, where the 150MB+ .jsonl is local, and streams back only the filtered result.
#
# Usage: extract-retro.sh <container> <since-iso> <until-iso> [outfile]
#   extract-retro.sh vesta-lucadv-gianfranco 2026-08-17T17:03:00 2026-08-17T17:25:00 retro.txt
# Timestamps are UTC, inclusive, string-compared, so keep them zero-padded.
set -euo pipefail

CONTAINER="${1:?container name required}"
SINCE="${2:?since ISO timestamp required}"
UNTIL="${3:?until ISO timestamp required}"
OUT="${4:-/dev/stdout}"
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"

# The agent persists its live session id; the transcript is named after it.
SESSION="$(sudo docker exec "$CONTAINER" cat /root/agent/data/state.json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')"
JSONL="$(sudo docker exec "$CONTAINER" sh -c "ls /root/.claude/projects/*/${SESSION}.jsonl 2>/dev/null | head -1")"
if [ -z "$JSONL" ]; then
  echo "no session transcript for $SESSION in $CONTAINER" >&2
  exit 1
fi

sudo docker cp "$SKILL_DIR/extract-transcript.py" "$CONTAINER:/tmp/extract-transcript.py"
# Capture, then write with an unprivileged redirect, so the redirect is not sudo's (SC2024).
result="$(sudo docker exec -e JSONL="$JSONL" -e SINCE="$SINCE" -e UNTIL="$UNTIL" \
  "$CONTAINER" /root/agent/.venv/bin/python /tmp/extract-transcript.py)"
printf '%s\n' "$result" >"$OUT"
sudo docker exec "$CONTAINER" rm -f /tmp/extract-transcript.py
echo "wrote $OUT (session $SESSION)" >&2

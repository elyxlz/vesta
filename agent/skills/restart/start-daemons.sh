#!/usr/bin/env bash
# Start every daemon listed in daemons.sh, read from the file on disk.
#
# The list is read from the file, never retyped from context: a context snapshot of this skill can
# lag the file by a line, and a daemon on the missing line would then never start while every line
# you can see reports green. Each line runs, so a line that is not a working daemon command exits
# non-zero and is reported as a failure, never silently skipped. Idempotent: a daemon already up
# answers already_running and spawns nothing, and each start returns only once its daemon is up, so
# the lines never race.
set -uo pipefail

LIST="$(cd "$(dirname "$0")" && pwd)/daemons.sh"

if [ ! -f "$LIST" ]; then
  echo "no daemon list at $LIST, nothing to start"
  exit 0
fi

mapfile -t lines < <(grep -vE '^[[:space:]]*(#|$)' "$LIST")

if [ "${#lines[@]}" -eq 0 ]; then
  echo "no daemons in $LIST, nothing to start"
  exit 0
fi

fail=0
for cmd in "${lines[@]}"; do
  name="${cmd%% *}"
  # A start whose readiness probe times out under transient host-load contention often succeeds
  # moments later once load subsides. A start is idempotent, so retry a failed line once after a
  # short pause before declaring the daemon down.
  for attempt in 1 2; do
    if out="$(sh -c "$cmd" 2>&1)"; then
      printf '%-12s %s\n' "$name" "$(printf '%s' "$out" | tr -d '\n')"
      break
    fi
    if [ "$attempt" -eq 2 ]; then
      printf '%-12s FAILED: %s\n' "$name" "$(printf '%s' "$out" | tr -d '\n')" >&2
      fail=1
    else
      sleep 2
    fi
  done
done

[ "$fail" -eq 0 ] || echo "one or more daemons did not come up" >&2
exit "$fail"

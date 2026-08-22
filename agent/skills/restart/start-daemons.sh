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

# Every skill CLI lives in ~/.local/bin, and nothing guarantees the CALLER put it on PATH: being
# invoked from a minimal-PATH shell is normal. A missing PATH entry and a dead daemon are
# indistinguishable in this script's output, which is why this belongs here rather than in the
# caller. Prepending only ADDS a location, so a genuinely absent CLI still fails loudly.
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) PATH="$HOME/.local/bin:$PATH"; export PATH ;;
esac

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

# DELIBERATELY NO `export DAEMON_READY_TIMEOUT_SECS` HERE. Most daemons on the list read it and
# their defaults differ by an order of magnitude, so one global value silently CUTS the budget for
# whichever daemon had the longest default, on the boot where it is needed most. A caller cannot
# express "raise the floor, never lower anyone's own default", because it does not know each
# daemon's default. The budget belongs to each daemon, next to the constant it overrides.

# A per-line BEGIN/END trace: a blocked daemon start and a hang in the harness's tool layer look
# identical from outside, and no daemon log here is timestamped. An unmatched BEGIN names the line
# in flight. NOT under data/daemons/: boot empties that directory before any daemon runs, so a
# trace there is destroyed by the restart that follows the very hang it exists to attribute. One
# previous generation is kept so a crash-restart leaves the hung run's trace in .prev.
TRACE="$HOME/agent/data/daemon-start-progress.log"
mkdir -p "$(dirname "$TRACE")"
[ -f "$TRACE" ] && mv -f "$TRACE" "$TRACE.prev"
: > "$TRACE"
trace() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$TRACE"; }
trace "RUN start-daemons.sh (${#lines[@]} lines)"

fail=0
for cmd in "${lines[@]}"; do
  name="${cmd%% *}"
  trace "BEGIN $name"
  if out="$(sh -c "$cmd" 2>&1)"; then
    printf '%-12s %s\n' "$name" "$(printf '%s' "$out" | tr -d '\n')"
  else
    printf '%-12s FAILED: %s\n' "$name" "$(printf '%s' "$out" | tr -d '\n')" >&2
    fail=1
  fi
  trace "END   $name"
done
trace "DONE fail=$fail"

[ "$fail" -eq 0 ] || echo "one or more daemons did not come up" >&2
exit "$fail"

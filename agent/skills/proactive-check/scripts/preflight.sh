#!/bin/sh
# The proactive check's two preflights, as one command: are the daemons alive, and what is left of
# the budget. Both are prose in SKILL.md, and prose is what an agent reconstructs from memory after
# a compaction rather than reads. This exists because that reconstruction is silently lossy: the
# budget check in particular degraded into `grep utilization ~/agent/logs/vesta.log` and ran that
# way on every tick for five days, against a skill that says in as many words not to. It kept
# looking fine because the log's number was close enough to the real one to never contradict it.
#
# Prints one line per daemon, one line per budget meter, and the band to spend at. Exits non-zero
# if anything needs attention, so a caller can branch on it.

red=0
ok() { printf 'OK    %s\n' "$1"; }
bad() {
    printf 'CHECK %s\n' "$1"
    red=$((red + 1))
}

# --- Daemons -----------------------------------------------------------------------------------
# The list comes from the restart skill, so a daemon never added there is invisible here; the
# second grep prints any start line that has no status verb to ask, as unchecked rather than
# healthy.
restart_skill="$HOME/agent/skills/restart/SKILL.md"
if [ ! -r "$restart_skill" ]; then
    bad "cannot read $restart_skill, so no daemon is checked at all"
else
    grep -E '^[a-z0-9-]+ daemon start' "$restart_skill" | while IFS= read -r line; do
        query=$(printf '%s' "$line" | sed -E 's/^([a-z0-9-]+ daemon )start/\1status/')
        out=$(sh -c "$query" 2>&1)
        rc=$?
        case "$out" in
            *'"running": true'* | *'"running":true'*) [ "$rc" -eq 0 ] && st=OK || st=CHECK ;;
            *) st=CHECK ;;
        esac
        printf '%-5s %-46s %s\n' "$st" "$query" "$(printf '%s' "$out" | tr -d '\n' | cut -c1-50)"
    done
    # A non-daemon start line has no status verb, so it is out of scope, not passing.
    grep -E '^[a-z0-9-]+ (start|serve)' "$restart_skill" | grep -v ' daemon start' \
        | while IFS= read -r line; do
            printf 'UNCHK %s (no status verb: check by hand)\n' "$line"
        done
fi

# --- Budget ------------------------------------------------------------------------------------
# Read the live meters, never the log. The log only carries rate-limit lines while a limit is being
# warned about, so after a window resets its last high number sits there looking current, and
# `resets_at` (the field that decides whether throttling is even worth it) is not in the log at all.
if [ -r /run/vestad-env ]; then
    . /run/vestad-env
fi
if [ -z "${WS_PORT:-}" ] || [ -z "${AGENT_TOKEN:-}" ]; then
    bad "no WS_PORT/AGENT_TOKEN, so the budget is UNKNOWN: do not assume there is headroom"
else
    usage_json=$(curl -s --max-time 10 "http://127.0.0.1:$WS_PORT/usage" -H "X-Agent-Token: $AGENT_TOKEN" 2>/dev/null)
    if [ -z "$usage_json" ]; then
        bad "the usage endpoint returned nothing, so the budget is UNKNOWN: treat it as tight, not as fine"
    else
        report=$(printf '%s' "$usage_json" | python3 -c '
import json, sys

try:
    meters = json.load(sys.stdin).get("meters") or []
except Exception as exc:
    print(f"UNPARSEABLE {exc}")
    raise SystemExit(0)

if not meters:
    # An empty list is not "plenty left", it is a reading that never happened.
    print("UNPARSEABLE the usage endpoint listed no meters")
    raise SystemExit(0)

worst = 0.0
for m in meters:
    raw = m.get("used_pct")
    pct = float(raw) if isinstance(raw, (int, float)) else 0.0
    worst = max(worst, pct)
    label = m.get("label") or "?"
    resets = m.get("resets_at") or "?"
    print("METER %s|%.0f|%s" % (label, pct, resets))
print("WORST %.0f" % worst)
' 2>/dev/null)

        case "$report" in
            UNPARSEABLE* | "")
                bad "could not read the usage meters (${report:-no output}): budget UNKNOWN, treat it as tight"
                ;;
            *)
                printf '%s\n' "$report" | while IFS= read -r line; do
                    case "$line" in
                        METER*)
                            rest=${line#METER }
                            label=${rest%%|*}
                            rest=${rest#*|}
                            pct=${rest%%|*}
                            resets=${rest#*|}
                            ok "budget: ${label} at ${pct}%, resets ${resets}"
                            ;;
                    esac
                done
                worst=$(printf '%s\n' "$report" | sed -n 's/^WORST //p')
                # Bands are on used_pct (0-100), NOT the 0-1 `utilization` fraction in vesta.log.
                if [ "${worst:-100}" -ge 80 ]; then
                    printf 'BAND  %s%% used: CHEAP TICKS ONLY. No research subagents at all. Write down what you would have done.\n' "$worst"
                elif [ "${worst:-100}" -ge 60 ]; then
                    printf 'BAND  %s%% used: no unrequested fan-outs. One focused agent only if genuinely urgent.\n' "$worst"
                else
                    printf 'BAND  %s%% used: normal, spend the tick as the work deserves.\n' "$worst"
                fi
                printf 'NOTE  overnight defaults one band stricter. Check resets_at: deferring past a near reset costs nothing.\n'
                ;;
        esac
    fi
fi

[ "$red" -gt 0 ] && exit 1
exit 0

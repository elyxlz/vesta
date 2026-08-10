#!/bin/sh
# The proactive check's preflight, as one command: are the daemons alive, and what is left of the
# budget. Prints one line per daemon, one line per budget meter, then the band to spend the tick at
# and whether a weekly deep dive is affordable. Exits non-zero if any line needs attention, so a
# caller can branch on it.
#
# This script, not the SKILL.md prose, owns the band policy: the thresholds and the wording of each
# band live in band() below and are stated nowhere else, so changing a threshold is one edit.

# Bands are on used_pct (0 to 100), the scale the /usage meters report. The `utilization` field in
# vesta.log is the same quantity as a 0-to-1 fraction, so the two must never be compared.
BAND_TIGHT_PCT=80
BAND_WATCH_PCT=60
USAGE_TIMEOUT_SECS=10

red=0
ok() { printf 'OK    %s\n' "$1"; }
bad() {
    printf 'CHECK %s\n' "$1"
    red=$((red + 1))
}

# --- Band policy ---------------------------------------------------------------------------------
# $1 is normal, watch or tight; $2 is the reading the tier came from.
band() {
    case "$1" in
        tight)
            printf 'BAND  tight (%s): cheap ticks only. Read state, do what is genuinely due, stop. No research subagents at all; write down what you would have done so a later tick picks it up.\n' "$2"
            printf 'DIVE  no: a weekly deep dive does not start in this band. It stays due, and the next quiet tick with headroom takes it.\n'
            ;;
        watch)
            printf 'BAND  watch (%s): no fan-outs the user did not ask for. One focused agent only if the work is genuinely urgent, otherwise do it in-thread or defer.\n' "$2"
            printf 'DIVE  no: a weekly deep dive does not start in this band. It stays due, and the next quiet tick with headroom takes it.\n'
            ;;
        *)
            printf 'BAND  normal (%s): spend the tick as the work deserves.\n' "$2"
            printf 'DIVE  yes: a deep dive that is due may run this tick, small hours included.\n'
            ;;
    esac
    printf 'NOTE  overnight is one band stricter, except a due deep dive: its slot is the small hours, so the bump would leave it no slot at all.\n'
    printf 'NOTE  check resets_at before rationing, since deferring past a near reset costs nothing.\n'
    printf 'NOTE  these windows are not the whole limit. A monthly spend cap refuses turns with no meter here, so a green band says the windows are fine, never that the next turn is allowed.\n'
}

# --- Daemons -------------------------------------------------------------------------------------
# The list comes from the restart skill, so a daemon never added there is invisible here. Only the
# `<skill> daemon start` form has a status verb to ask; any other start line is printed as unchecked
# rather than passing silently.
restart_skill="$HOME/agent/skills/restart/SKILL.md"
if [ ! -r "$restart_skill" ]; then
    bad "cannot read $restart_skill, so no daemon is checked at all"
else
    daemon_lines=$(grep -E '^[a-z0-9-]+ daemon start' "$restart_skill")
    other_lines=$(grep -E '^[a-z0-9-]+ (start|serve)' "$restart_skill" | grep -v ' daemon start')
    if [ -z "$daemon_lines" ] && [ -z "$other_lines" ]; then
        ok "the restart skill lists no daemons yet, so there is none to check"
    fi
    # Fed by redirect, never by a pipe: a `grep | while` loop runs in a subshell, where every red
    # this loop counts is discarded and a dead daemon exits 0.
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        query=$(printf '%s' "$line" | sed -E 's/^([a-z0-9-]+ daemon )start/\1status/')
        out=$(sh -c "$query" 2>&1)
        rc=$?
        summary=$(printf '%s' "$out" | tr -d '\n' | cut -c1-60)
        case "$out" in
            *'"running": true'* | *'"running":true'*)
                if [ "$rc" -eq 0 ]; then
                    ok "$query: $summary"
                else
                    bad "$query exited $rc: $summary"
                fi
                ;;
            *) bad "$query: ${summary:-no output}" ;;
        esac
    done <<EOF
$daemon_lines
EOF
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        printf 'UNCHK %s (no status verb to ask: check this one by hand)\n' "$line"
    done <<EOF
$other_lines
EOF
fi

# --- Budget --------------------------------------------------------------------------------------
# Read the live meters, never vesta.log: the log carries rate-limit lines only while a limit is
# being warned about, so after a window resets its last high number sits there looking current, and
# resets_at is not in the log at all.
if [ -z "${WS_PORT:-}" ] || [ -z "${AGENT_TOKEN:-}" ]; then
    if [ -r /run/vestad-env ]; then
        . /run/vestad-env
    fi
fi
if [ -z "${WS_PORT:-}" ] || [ -z "${AGENT_TOKEN:-}" ]; then
    bad "no WS_PORT/AGENT_TOKEN, so the budget cannot be measured at all"
    band tight "budget unmeasurable"
else
    response=$(curl -s --max-time "$USAGE_TIMEOUT_SECS" -w '\n%{http_code}' \
        "http://127.0.0.1:$WS_PORT/usage" -H "X-Agent-Token: $AGENT_TOKEN" 2>/dev/null)
    http_code=$(printf '%s\n' "$response" | tail -n 1)
    payload=$(printf '%s\n' "$response" | sed '$d')
    if [ "$http_code" != "200" ]; then
        bad "the usage endpoint answered ${http_code:-nothing}, so the budget is unmeasurable: ration rather than assume headroom"
        band tight "budget unmeasurable"
    else
        report=$(printf '%s' "$payload" | python3 -c '
import json
import sys

# Three states, not two. A provider that reports no budget is not a budget that could not be read:
# core answers 200 with meters=[] and credits=null for every provider without per-window metering
# (provider.py get_usage), and 200 with meters=[] and a filled credits for OpenRouter. Folding
# either into "unknown" rations those agents on every tick forever, and the second throws away a
# measured budget sitting in the payload already fetched.


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def field(obj, key):
    return obj[key] if isinstance(obj, dict) and key in obj else None


raw = sys.stdin.read()
try:
    payload = json.loads(raw)
except ValueError as exc:
    print("UNMEASURABLE the usage payload is not JSON (%s)" % exc)
    raise SystemExit(0)
if not isinstance(payload, dict):
    print("UNMEASURABLE the usage payload is not an object")
    raise SystemExit(0)
if "error" in payload:
    print("UNMEASURABLE the usage endpoint reported an error (%s)" % payload["error"])
    raise SystemExit(0)

meters = payload["meters"] if "meters" in payload else None
credits = payload["credits"] if "credits" in payload else None
if meters is None or not isinstance(meters, list):
    print("UNMEASURABLE the usage payload carries no meters list")
    raise SystemExit(0)

worst = None
unreadable = False
for meter in meters:
    label = field(meter, "label")
    label = label if isinstance(label, str) else "unnamed meter"
    resets = field(meter, "resets_at")
    resets = resets if isinstance(resets, str) else "unknown"
    pct = field(meter, "used_pct")
    # A null used_pct is legal in the schema. Reading it as zero prints a reassuring band off a
    # meter nobody measured, so it is reported and left out of the worst-case instead.
    if not numeric(pct):
        unreadable = True
        print("UNREADABLE %s reports no usable used_pct" % label)
        continue
    worst = float(pct) if worst is None else max(worst, float(pct))
    print("METER %s|%.0f|%s" % (label, float(pct), resets))

# Credits fold into worst like any other meter, they are NOT a fallback for when meters are
# missing. A provider can report both (Claude with extra usage enabled reports rate windows AND a
# monthly spend balance), and a monthly cap at 95% beside a session window at 20% must band on the
# 95. The budget is the WORST of every signal, never the first one that happens to parse.
used, limit = field(credits, "used"), field(credits, "limit")
if numeric(used) and numeric(limit) and limit > 0:
    pct = 100.0 * float(used) / float(limit)
    worst = pct if worst is None else max(worst, pct)
    print("METER credits, %.2f of %.2f spent|%.0f|n/a" % (used, limit, pct))

if worst is not None:
    print("WORST %.0f" % worst)
elif unreadable:
    print("UNMEASURABLE no meter reported a usable used_pct")
else:
    print("UNMETERED")
' 2>&1)

        case "$report" in
            *UNMEASURABLE*)
                bad "the usage payload could not be read ($(printf '%s' "$report" | tr '\n' ';')): the budget is unmeasurable, so ration rather than assume headroom"
                band tight "budget unmeasurable"
                ;;
            UNMETERED)
                ok "this provider reports no meters and no credit limit, so there is no budget to ration against"
                band normal "no budget reported"
                ;;
            *WORST*)
                while IFS= read -r line; do
                    case "$line" in
                        METER*)
                            rest=${line#METER }
                            label=${rest%%|*}
                            rest=${rest#*|}
                            ok "budget: ${label} at ${rest%%|*}%, resets ${rest#*|}"
                            ;;
                        UNREADABLE*) bad "budget: ${line#UNREADABLE }, so this window is not covered by the band below" ;;
                    esac
                done <<EOF
$report
EOF
                worst=$(printf '%s\n' "$report" | sed -n 's/^WORST //p')
                if [ "${worst:-100}" -ge "$BAND_TIGHT_PCT" ]; then
                    band tight "${worst}% used"
                elif [ "${worst:-100}" -ge "$BAND_WATCH_PCT" ]; then
                    band watch "${worst}% used"
                else
                    band normal "${worst}% used"
                fi
                ;;
            *)
                bad "the usage reader produced no verdict (${report:-no output}): the budget is unmeasurable, so ration rather than assume headroom"
                band tight "budget unmeasurable"
                ;;
        esac
    fi
fi

# --- Reality-check watchdog ----------------------------------------------------------------------
# reality_check.sh carries the probe that detects a missed dream, and the dream is the only thing
# that runs reality_check.sh, so a missed night takes its own detector down with it. This tick is
# daemon-driven and fires whether or not anything is remembered, so it is the one place the probe
# can be re-run from. A recent run leaves a fresh record and this stays silent, costing one file
# read.
RC_HIST="$HOME/agent/data/reality-history.tsv"
RC_STAMP="$HOME/agent/data/reality-watchdog.stamp"
RC_SCRIPT="$HOME/agent/skills/dream/scripts/reality_check.sh"
RC_STALE_HOURS=25

# Whole hours since an ISO-8601 stamp, or 999 when there is nothing readable to age.
rc_age_hours() {
    [ -n "$1" ] || {
        echo 999
        return
    }
    rc_epoch=$(date -u -d "$1" +%s 2>/dev/null)
    [ -n "$rc_epoch" ] || {
        echo 999
        return
    }
    echo $((($(date -u +%s) - rc_epoch) / 3600))
}

if [ -f "$RC_SCRIPT" ]; then
    rc_last=""
    [ -s "$RC_HIST" ] && rc_last=$(tail -n 1 "$RC_HIST" | cut -f1)
    rc_age=$(rc_age_hours "$rc_last")
    # Not every box keeps a run record, so the watchdog stamps its own runs and ages by whichever
    # record is newer. Without the stamp, a box with no record re-runs the probe every tick.
    rc_stamp_age=$(rc_age_hours "$(cat "$RC_STAMP" 2>/dev/null)")
    [ "$rc_stamp_age" -lt "$rc_age" ] && rc_age=$rc_stamp_age
    if [ "$rc_age" -ge "$RC_STALE_HOURS" ]; then
        printf 'WATCHDOG the reality check last ran %sh ago (>= %sh): running it now, because the dream that normally runs it may have been missed.\n' "$rc_age" "$RC_STALE_HOURS"
        rc_out=$(sh "$RC_SCRIPT" 2>&1)
        rc_status=$?
        mkdir -p "$(dirname "$RC_STAMP")" 2>/dev/null
        date -u +%Y-%m-%dT%H:%M:%SZ > "$RC_STAMP" 2>/dev/null || true
        # Judged by the probe's exit code, which is its contract, never by grepping its output for
        # '^RED': any summary line opening with that word then reads as a finding of its own.
        printf '%s\n' "$rc_out" | grep -E '^RED [a-z]' || true
        if [ "$rc_status" -ne 0 ]; then
            bad "the reality check exited ${rc_status} with the REDs above, after ${rc_age}h without running"
        else
            printf 'WATCHDOG the reality check ran clean (exit 0).\n'
        fi
    fi
else
    bad "reality_check.sh is missing at $RC_SCRIPT: the probe that catches silent failures is itself absent"
fi

if [ "$red" -gt 0 ]; then
    printf '%s CHECK: each one is a real finding; clear it before spending the tick.\n' "$red"
    exit 1
fi
printf 'all preflight checks green\n'
exit 0

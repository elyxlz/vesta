#!/bin/sh
# Probe the running system before the retrospective: the dream's record only holds what was written
# down, so a dead daemon, a full disk, or an error storm nobody logged is invisible to it. Prints
# one OK/RED line per probe and exits 1 if anything is RED. Probes read only fleet-generic state
# (daemon records, logs, disk, the events DB, the notifications dir), so a RED is real on any box.

# Disk-probe knobs: the agent's own footprint is RED only when the filesystem is also under real
# pressure (or the pressure reading failed, which cannot prove it absent); the host nearing full is
# RED on its own, since writes start failing across the box. Note the host's percentage as context
# in between, and bound the du walk so a pathological tree or a stuck filesystem can never hang the
# dream that runs this probe.
OWN_USAGE_RED_MB=20000
HOST_DISK_NOTE_PERCENT=90
HOST_DISK_RED_PERCENT=97
# Own-usage alone is a size, not a problem: an agent whose job is a document corpus can sit on tens
# of GB forever on a disk that is two thirds empty, and then this probe is RED every single night
# with nothing to clear. A permanent RED is worse than no probe, because it teaches you to skim the
# one output that exists to stop you skimming. So own usage only turns RED when the filesystem is
# ALSO under real pressure; below that it prints as context.
HOST_DISK_PRESSURE_PERCENT=85
DU_TIMEOUT_SECS=120

red=0
ok() { printf 'OK  %s\n' "$1"; }
bad() {
    printf 'RED %s\n' "$1"
    red=$((red + 1))
}

# Daemon records: boot clears stale records, so a recorded pid with no process died since boot and
# nothing restarted it. The record is "<pid> <starttime>", so the pid is its first field.
for pid_file in "$HOME"/agent/data/daemons/*.pid; do
    [ -e "$pid_file" ] || continue
    name=$(basename "$pid_file" .pid)
    record=$(cat "$pid_file" 2>/dev/null)
    if kill -0 "${record%% *}" 2>/dev/null; then
        ok "daemon $name is running"
    else
        bad "daemon $name has a record but no process: it died and nothing restarted it"
    fi
done

# Disk: a full disk fails writes quietly all over the box, never loudly in one place. On a shared
# host the filesystem under $HOME is the host's, so its percentage is mostly other tenants and no
# amount of cleanup here moves it, so report it as context rather than a RED. Past the ceiling that
# stops being true: not yours to clear is not the same as not your problem, because writes start
# failing across the box, so that one is a RED to escalate rather than to fix here.
usage=$(df -P "$HOME" | awk 'NR==2 {gsub("%","",$5); print $5}')
du_lines=$(timeout "$DU_TIMEOUT_SECS" du -sm "$HOME" /tmp 2>/dev/null)
du_status=$?
mine=$(printf '%s\n' "$du_lines" | awk '{t+=$1} END {print t+0}')
# Two independent facts, reported independently: a large own footprint must not suppress the host
# reading, because the night both are true is the night the host figure matters most.
if [ "$du_status" -eq 124 ]; then
    bad "sizing \$HOME and /tmp took over ${DU_TIMEOUT_SECS}s: the tree is enormous or a filesystem is stuck; investigate tonight"
    mine_str="an unmeasured share"
elif [ "${mine:-0}" -ge "$OWN_USAGE_RED_MB" ] && { [ -z "${usage:-}" ] || [ "$usage" -ge "$HOST_DISK_PRESSURE_PERCENT" ]; }; then
    # An empty usage means df failed, so pressure is unknown, and unknown must not read as absent:
    # a probe that fails open on its own instrument breaking is the silent failure it exists to catch.
    bad "disk at ${usage:-unknown}% and this agent holds ${mine}MB of it: clean up tonight (workspace cleanup)"
elif [ "${mine:-0}" -ge "$OWN_USAGE_RED_MB" ]; then
    ok "this agent holds ${mine}MB, but the disk is only at ${usage}%: size without pressure, nothing to clear"
fi
# On a du timeout the footprint is unknown, so the host lines must not quote a figure of 0MB that
# would read as "none of this is mine".
mine_str="${mine_str:-${mine:-0}MB}"

# Naming an actor who cannot act is the same as naming none: vestad has no surface that frees host
# disk, so the escalation is to the user, who is the only party able to clear another tenant's space.
if [ "${usage:-0}" -ge "$HOST_DISK_RED_PERCENT" ]; then
    bad "host disk at ${usage}% with ${mine_str} of it this agent's: cleanup here cannot fix it, so tell the user tonight; writes will start failing across the box"
elif [ "${usage:-0}" -ge "$HOST_DISK_NOTE_PERCENT" ]; then
    ok "host disk at ${usage}%, ${mine_str} of it this agent's; the rest is the host, not yours to clear"
else
    ok "host disk at ${usage:-unknown}%, ${mine_str} of it this agent's"
fi

# Error storms: a component can log thousands of errors without one of them reaching a notification.
#
# Count only lines DATED within the last two days, not simply the last 2000 lines. The freshness
# test used to be on the file while the count was over its tail, so a log that had been fixed still
# reported RED until enough healthy lines pushed the old errors out of the window. Seen 8 Aug 2026:
# apple-calendar re-authed on 6 Aug and had synced cleanly every 5 min since, yet 1,962 pre-fix
# Unauthorized lines sat in the tail and it would have kept crying RED for about three more days.
# A check that stays loud after the fix is how a real RED gets waved off as stale.
rc_today=$(date +%F)
rc_yest=$(date -d yesterday +%F 2>/dev/null || date -v-1d +%F 2>/dev/null)
for log in "$HOME"/agent/logs/*.log; do
    [ -e "$log" ] || continue
    [ -n "$(find "$log" -mmin -1440 2>/dev/null)" ] || continue
    window=$(tail -n 2000 "$log")
    # A healthy summary line such as "45 matching, 0 new, 0 error(s)" carries the word without
    # reporting a failure, so drop zero-count lines before counting. Only lines whose sole count is
    # zero: "0 warnings, 47 errors" and "worker 0 error: connection refused" are real signal, so a
    # line naming a nonzero count, or using the bare singular, is kept.
    signal=$(printf '%s\n' "$window" | awk '{ low = tolower($0) }
        !((low ~ /(^|[^0-9])0 (errors|error\(s\)|warnings|warning\(s\))/ || low ~ /no errors/) && low !~ /[1-9][0-9]* (error|warning)/)')
    # Logs whose lines carry no leading ISO date can't be aged; count them whole and say so, rather
    # than silently reporting zero for a component that is genuinely storming.
    # Accept an optional leading '[': several daemons bracket their timestamps, and anchoring on a
    # bare digit demotes those logs to "undated", so their whole tail is counted and a component
    # that recovers long ago keeps reporting RED with no way to age the old lines out.
    dated=$(printf '%s\n' "$window" | grep -cE '^\[?[0-9]{4}-[0-9]{2}-[0-9]{2}' || true)
    if [ "${dated:-0}" -gt 0 ]; then
        # An undated line inherits the recency of the dated line above it: a traceback's body has
        # no timestamp of its own, and requiring the date on every line hid whole live storms.
        errors=$(printf '%s\n' "$signal" | awk -v today="$rc_today" -v yest="$rc_yest" '
            /^\[?[0-9]{4}-[0-9]{2}-[0-9]{2}/ { recent = ($0 ~ "^\\[?"today) || ($0 ~ "^\\[?"yest) }
            recent' | grep -icE 'error|traceback' || true)
        span="in the last 2 days"
    else
        errors=$(printf '%s\n' "$signal" | grep -icE 'error|traceback' || true)
        span="in its recent tail (undated log, age unknown)"
    fi
    if [ "${errors:-0}" -gt 200 ]; then
        bad "$(basename "$log"): $errors error lines $span; read it and find the producer"
    else
        ok "$(basename "$log"): $errors error lines $span"
    fi
done

# UNPROTECTED HAND-MADE STATE. Every other probe takes its scope as an input (a list of daemons, a
# list of logs), so a store nobody thought to list is invisible to all of them by construction. This
# one derives its own scope: ask the filesystem what changed in the last week, subtract what git
# tracks, subtract what an agent/*-snapshot/ dir already mirrors as readable text, subtract caches
# and credentials, report the remainder. Credentials are dropped on purpose: they must never be
# committed, and the artefact for them is a reissue path, not a backup. unprotected-accepted.txt
# beside this script records exposures already judged, so a NEW store still goes RED.
if command -v git >/dev/null 2>&1 && [ -d "$HOME/.git" ]; then
    accepted_list="$(dirname "$0")/unprotected-accepted.txt"
    snapshotted=$(git -C "$HOME" ls-files 'agent/*-snapshot/*' 2>/dev/null)
    unprotected=$(
        find "$HOME" -maxdepth 3 -type f \
            \( -name '*.json' -o -name '*.db' -o -name '*.sqlite' -o -name '*.md' -o -name '*.yaml' -o -name '*.toml' \) \
            -mtime -7 2>/dev/null \
        | grep -vE '/(\.git|\.cache|\.npm|\.venv|node_modules|__pycache__|\.ruff_cache|go/pkg|dist|build|\.local/share/uv|\.claude/(projects|sessions|shell-snapshots|backups|session-env))/' \
        | grep -vE "^$HOME/(agent/(core|notifications|logs)/|scratch/|Downloads/|\.browser/|\.camoufox/|\.microsoft/emails/)" \
        | grep -vE '(credentials|auth_cache|cookies\.sqlite|key4\.db)' \
        | while read -r f; do
            rel=${f#"$HOME"/}
            git -C "$HOME" ls-files --error-unmatch "$rel" >/dev/null 2>&1 && continue
            printf '%s\n' "$snapshotted" | grep -qF -- "$(basename "$f")" && continue
            grep -v '^#' "$accepted_list" 2>/dev/null | grep -qxF -- "$rel" && continue
            printf '%s\n' "$rel"
        done
    )
    if [ -n "$unprotected" ]; then
        count=$(printf '%s\n' "$unprotected" | wc -l | tr -d ' ')
        bad "$count hand-made file(s) changed in 7d are neither tracked nor mirrored: $(printf '%s' "$unprotected" | tr '\n' ' ' | cut -c1-300)"
    else
        ok "no unprotected hand-made state changed in the last 7 days"
    fi
fi

# Events DB freshness: the store is written on every turn, but it runs in WAL mode, so between
# checkpoints the recent commits touch only the -wal sibling; judge by the newest of the pair.
db="$HOME/agent/data/events.db"
if [ ! -e "$db" ]; then
    bad "events.db missing at $db"
elif [ -n "$(find "$db" "$db-wal" -mmin -1440 2>/dev/null)" ]; then
    ok "events.db written within 24h"
else
    bad "events.db untouched for over 24h: events are not being recorded"
fi

# Notifications dir: if this is not writable, every producer on the box is silently mute.
notif="$HOME/agent/notifications"
if mkdir -p "$notif" 2>/dev/null && touch "$notif/.reality_check" 2>/dev/null; then
    rm -f "$notif/.reality_check"
    ok "notifications dir is writable"
else
    bad "notifications dir is not writable: every producer is silently mute"
fi

# Did the dream itself lapse? Keyed on the summary file, never on a checkpoint commit message: a
# summary is written on every run however that run's commit was worded, so its mtime is the honest
# signal while a grep for exact wording silently misses a run that used other words. 30h, not 24h,
# because a normal cadence is exactly 24h and a run an hour late would false-RED at that bound;
# a fully missed night shows up as ~48h, so 30h catches it with margin.
DREAM_LAPSE_HOURS=30
dreamdir="$HOME/agent/dreamer"
newest=$(ls -t "$dreamdir"/*.md 2>/dev/null | head -1)
if [ -z "$newest" ]; then
    ok "no dreamer summaries yet, so there is no cadence to have broken"
else
    age_h=$(( ( $(date +%s) - $(date -r "$newest" +%s) ) / 3600 ))
    if [ "$age_h" -ge "$DREAM_LAPSE_HOURS" ]; then
        bad "last dreamer summary is ${age_h}h old (>= ${DREAM_LAPSE_HOURS}h): a night was missed, and nothing else would have told me"
    else
        ok "last dreamer summary ${age_h}h old, cadence intact"
    fi
fi

# Append-only history. A single run can only say "how many REDs right now", which is the same
# one-night horizon that let this probe silently stop being run for three nights in Aug 2026
# without anyone noticing. Recording every run means the SERIES is checkable and, more importantly,
# a GAP in it is itself the finding: the gauge cannot quietly lapse without leaving a hole.
rc_hist="$HOME/agent/data/reality-history.tsv"
mkdir -p "$(dirname "$rc_hist")" 2>/dev/null
# Read the previous run's timestamp BEFORE appending this one: read after, the line always shows
# "now" and the gap the series exists to expose can never appear in the output.
prev_run=$(tail -n 1 "$rc_hist" 2>/dev/null | cut -f1)
printf '%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$red" >> "$rc_hist"

prior=$(tail -n 6 "$rc_hist" 2>/dev/null | awk '{printf "%s ", $2}')
[ -n "$prior" ] && printf 'flagged-probe count over recent runs (oldest first): %s\n' "$prior"
[ -n "$prev_run" ] && printf 'previous run recorded: %s\n' "$prev_run"

if [ "$red" -gt 0 ]; then
    printf '%s RED: fix each tonight or write the reason off in the summary.\n' "$red"
    exit 1
fi
printf 'all probes green\n'
exit 0

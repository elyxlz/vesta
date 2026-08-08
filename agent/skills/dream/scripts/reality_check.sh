#!/bin/sh
# Probe the running system before the retrospective: the dream's record only holds what was written
# down, so a dead daemon, a full disk, or an error storm nobody logged is invisible to it. Prints
# one OK/RED line per probe and exits 1 if anything is RED. Probes read only fleet-generic state
# (daemon records, logs, disk, the events DB, the notifications dir), so a RED is real on any box.

# Disk-probe knobs: RED once this agent's own files could plausibly fill a disk, note the host's
# percentage as context past the note threshold, and bound the du walk so a pathological tree or a
# stuck filesystem can never hang the dream that runs this probe.
OWN_USAGE_RED_MB=20000
HOST_DISK_NOTE_PERCENT=90
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
# amount of cleanup here moves it. RED only on what this agent can actually act on, and report the
# host figure as context, so the probe never hands you a RED you cannot clear.
usage=$(df -P "$HOME" | awk 'NR==2 {gsub("%","",$5); print $5}')
du_lines=$(timeout "$DU_TIMEOUT_SECS" du -sm "$HOME" /tmp 2>/dev/null)
du_status=$?
mine=$(printf '%s\n' "$du_lines" | awk '{t+=$1} END {print t+0}')
if [ "$du_status" -eq 124 ]; then
    bad "sizing \$HOME and /tmp took over ${DU_TIMEOUT_SECS}s: the tree is enormous or a filesystem is stuck; investigate tonight"
elif [ "${mine:-0}" -ge "$OWN_USAGE_RED_MB" ]; then
    bad "this agent is using ${mine}MB across \$HOME and /tmp: clean up tonight (workspace cleanup)"
elif [ "${usage:-0}" -ge "$HOST_DISK_NOTE_PERCENT" ]; then
    ok "disk at ${usage}% but only ${mine}MB is this agent's; the rest is the host, not yours to clear"
else
    ok "disk at ${usage:-unknown}%, ${mine}MB of it this agent's"
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
    # Logs whose lines carry no leading ISO date can't be aged; count them whole and say so, rather
    # than silently reporting zero for a component that is genuinely storming.
    # Accept an optional leading '[': several daemons bracket their timestamps, and anchoring on a
    # bare digit demotes those logs to "undated", so their whole tail is counted and a component
    # that recovers long ago keeps reporting RED with no way to age the old lines out.
    dated=$(printf '%s\n' "$window" | grep -cE '^\[?[0-9]{4}-[0-9]{2}-[0-9]{2}' || true)
    if [ "${dated:-0}" -gt 0 ]; then
        errors=$(printf '%s\n' "$window" | grep -E "^\[?($rc_today|$rc_yest)" | grep -icE 'error|traceback' || true)
        span="in the last 2 days"
    else
        errors=$(printf '%s\n' "$window" | grep -icE 'error|traceback' || true)
        span="in its recent tail (undated log, age unknown)"
    fi
    if [ "${errors:-0}" -gt 200 ]; then
        bad "$(basename "$log"): $errors error lines $span; read it and find the producer"
    else
        ok "$(basename "$log"): $errors error lines $span"
    fi
done

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

# Append-only history. A single run can only say "how many REDs right now", which is the same
# one-night horizon that let this probe silently stop being run for three nights in Aug 2026
# without anyone noticing. Recording every run means the SERIES is checkable and, more importantly,
# a GAP in it is itself the finding: the gauge cannot quietly lapse without leaving a hole.
rc_hist="$HOME/agent/data/reality-history.tsv"
mkdir -p "$(dirname "$rc_hist")" 2>/dev/null
printf '%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$red" >> "$rc_hist"

prior=$(tail -n 6 "$rc_hist" 2>/dev/null | awk '{printf "%s ", $2}')
[ -n "$prior" ] && printf 'RED count over last runs (oldest first): %s\n' "$prior"
printf 'last run recorded: %s\n' "$(tail -n 1 "$rc_hist" | cut -f1)"

if [ "$red" -gt 0 ]; then
    printf '%s RED: fix each tonight or write the reason off in the summary.\n' "$red"
    exit 1
fi
printf 'all probes green\n'
exit 0

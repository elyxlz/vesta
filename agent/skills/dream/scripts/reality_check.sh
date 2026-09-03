#!/bin/sh
# Probe the running system before the retrospective: the dream's record only holds what was written
# down, so a dead daemon, a full disk, or an error storm nobody logged is invisible to it. Prints
# one OK/RED line per probe and exits 1 if anything is RED. Probes read only fleet-generic state
# (daemon records, logs, disk, the events DB, the notifications dir), so a RED is real on any box.

# Disk knobs: own usage is RED only while the host is also at the pressure percent, the host alone
# is RED at the RED percent, and the du walk is bounded so a stuck filesystem cannot hang the dream.
OWN_USAGE_RED_MB=20000
HOST_DISK_PRESSURE_PERCENT=85
HOST_DISK_RED_PERCENT=97
DU_TIMEOUT_SECS=120
# A nightly cadence is 24h and a missed night reads as 48h, so the lapse bound sits between them.
DREAM_LAPSE_HOURS=30
# One or two refused turns are a transient the next turn absorbs; three in a day is a window binding.
REFUSED_TURNS_RED=3

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

# Disk: a full disk fails writes quietly all over the box. The filesystem under $HOME is the host's,
# so its percentage is mostly other tenants: own usage is a RED to clear here only under host
# pressure, the host alone is a RED to escalate once writes are about to fail, reported separately.
usage=$(df -P "$HOME" | awk 'NR==2 {gsub("%","",$5); print $5}')
du_lines=$(timeout "$DU_TIMEOUT_SECS" du -sm "$HOME" /tmp 2>/dev/null)
du_status=$?
mine=$(printf '%s\n' "$du_lines" | awk '{t+=$1} END {print t+0}')
if [ "$du_status" -eq 124 ]; then share="unmeasured"; else share="${mine}MB"; fi
# A du walk a busy host starves says nothing about the disk; df decides whether the share matters.
if [ "$du_status" -eq 124 ] && [ "${usage:-0}" -ge "$HOST_DISK_PRESSURE_PERCENT" ]; then
    bad "sizing \$HOME and /tmp took over ${DU_TIMEOUT_SECS}s with the disk at ${usage}%: this agent's share is unmeasured while it matters; investigate tonight"
elif [ "$du_status" -eq 124 ]; then
    ok "sizing \$HOME and /tmp took over ${DU_TIMEOUT_SECS}s: footprint unmeasured, disk at ${usage:-unknown}%"
elif [ "${mine:-0}" -ge "$OWN_USAGE_RED_MB" ] && [ "${usage:-0}" -ge "$HOST_DISK_PRESSURE_PERCENT" ]; then
    bad "disk at ${usage}% and this agent holds ${mine}MB of it: clean up tonight (workspace cleanup)"
elif [ "${mine:-0}" -ge "$OWN_USAGE_RED_MB" ]; then
    ok "this agent holds ${mine}MB, but the disk is only at ${usage:-unknown}%: size without pressure, nothing to clear"
fi
if [ "${usage:-0}" -ge "$HOST_DISK_RED_PERCENT" ]; then
    bad "host disk at ${usage}%, $share of it this agent's: cleanup here cannot fix it, tell the user tonight; writes will start failing across the box"
elif [ "${usage:-0}" -ge "$HOST_DISK_PRESSURE_PERCENT" ]; then
    ok "host disk at ${usage}%, $share of it this agent's; the rest is the host, not yours to clear"
else
    ok "host disk at ${usage:-unknown}%, $share of it this agent's"
fi

# Error storms: a component can log thousands of errors without one of them reaching a notification.
# Only lines dated today or yesterday count (an undated line takes the date of the line above it),
# a line whose only count is zero ("0 error(s)", "no errors") reports success and is skipped, and
# the file's colour codes are stripped first so a dated line is seen as dated. vesta.log interleaves
# daemon output with the agent's own [AGENT] narration, which is prose, not a component's failure.
today=$(date +%F)
yesterday=$(date -d yesterday +%F)
esc=$(printf '\033')
for log in "$HOME"/agent/logs/*.log; do
    [ -e "$log" ] || continue
    [ -n "$(find "$log" -mmin -1440 2>/dev/null)" ] || continue
    errors=$(tail -n 2000 "$log" | sed "s/$esc\[[0-9;]*m//g" | awk -v today="$today" -v yesterday="$yesterday" '
        BEGIN { recent = 1 }
        /^\[?[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/ { recent = ($0 ~ ("^\\[?" today)) || ($0 ~ ("^\\[?" yesterday)) }
        { low = tolower($0) }
        recent && $0 !~ /\[AGENT\]/ && !((low ~ /(^|[^0-9])0 (errors|error\(s\)|warnings|warning\(s\))/ || low ~ /no errors/) && low !~ /[1-9][0-9]* (error|warning)/)' \
        | grep -icE 'error|traceback')
    if [ "$errors" -gt 200 ]; then
        bad "$(basename "$log"): $errors error lines in the last 2 days; read it and find the producer"
    else
        ok "$(basename "$log"): $errors error lines in the last 2 days"
    fi
done

# Refused turns: a turn the provider refused logs in=0 out=0 cache_read=0, since nothing ran, while
# a turn that ran and chose silence still reads its cache. That usage line is the one trace every
# refusal leaves, so count those lines rather than the daemon's rate-limit warnings.
refused=$(grep -h "$today .*\[USAGE\] in=0 out=0 cache_read=0 " "$HOME"/agent/logs/vesta.log* 2>/dev/null | wc -l)
if [ "$refused" -ge "$REFUSED_TURNS_RED" ]; then
    bad "the provider refused $refused turns today: each was a message or a job that never ran; find the window in vesta.log and what it dropped"
else
    ok "the provider refused $refused turns today"
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

# Dream cadence: every dream writes a summary, so no summary newer than the lapse bound means a night
# was missed; a box with no summaries yet has no cadence to break.
dreamer="$HOME/agent/dreamer"
if [ -z "$(find "$dreamer" -name '*.md' 2>/dev/null)" ]; then
    ok "no dreamer summaries yet, so there is no cadence to have broken"
elif [ -n "$(find "$dreamer" -name '*.md' -mmin -$((DREAM_LAPSE_HOURS * 60)) 2>/dev/null)" ]; then
    ok "a dreamer summary was written within ${DREAM_LAPSE_HOURS}h, cadence intact"
else
    bad "no dreamer summary written in ${DREAM_LAPSE_HOURS}h: a night was missed"
fi

if [ "$red" -gt 0 ]; then
    printf '%s RED: fix each tonight or write the reason off in the summary.\n' "$red"
    exit 1
fi
printf 'all probes green\n'
exit 0

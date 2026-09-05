#!/bin/sh
# Probe the running system before the retrospective: the dream's record only holds what was written
# down, so a dead daemon, a full disk, or an error storm nobody logged is invisible to it. Prints
# one OK/RED line per probe and exits 1 if anything is RED. Probes read only fleet-generic state
# (daemon records, logs, disk, the events DB, the notifications dir), so a RED is real on any box.

# Disk knobs: own usage is RED only while the host is also at the pressure percent, the host alone
# is RED at the RED percent, and the du walk is bounded so a stuck filesystem cannot hang the dream.
OWN_USAGE_RED_MB=20000
# Own-usage alone is a size, not a problem: an agent whose job is a document corpus can sit on tens
# of GB forever on a disk that is two thirds empty, and then this probe is RED every single night
# with nothing to clear. A permanent RED is worse than no probe, because it teaches you to skim the
# one output that exists to stop you skimming. So own usage only turns RED when the filesystem is
# ALSO under real pressure; below that it prints as context. The v0.3.0 split that idea into two
# thresholds and this file keeps theirs: PRESSURE is where own usage starts to matter, RED is where
# the host is about to fail writes and the news goes to the user instead of into a cleanup.
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
    # The recent, non-AGENT, not-a-success-line error lines. Computed ONCE, because the count and
    # the "most common" summary below MUST read the same population: the first version of this
    # summary re-derived its own lines with a bare grep, so it skipped both the date window and the
    # success-line filter, and on a fixture it happily reported "1 error" alongside "most common:
    # 50 ..." from six days earlier, and on another it reported a SUCCESS line ("sync finished:
    # 0 errors") as the dominant error, invisibly, because the digit-normalising sed had turned the
    # 0 into an N. A summary that reads a wider population than the number it annotates is worse
    # than no summary: it is a confident lead pointing away from the thing you are looking at.
    righe=$(tail -n 2000 "$log" | sed "s/$esc\[[0-9;]*m//g" | awk -v today="$today" -v yesterday="$yesterday" '
        BEGIN { recent = 1 }
        /^\[?[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/ { recent = ($0 ~ ("^\\[?" today)) || ($0 ~ ("^\\[?" yesterday)) }
        { low = tolower($0) }
        recent && $0 !~ /\[AGENT\]/ && !((low ~ /(^|[^0-9])0 (errors|error\(s\)|warnings|warning\(s\))/ || low ~ /no errors/) && low !~ /[1-9][0-9]* (error|warning)/)' \
        | grep -iE 'error|traceback')
    errors=$(printf '%s' "$righe" | grep -c . )
    # A bare count under the threshold reads as OK and tells you nothing about WHAT is failing.
    # On 5 Sep 2026 chat-mirror.log sat at 153 errors, comfortably under 200, and 148 of them were
    # one line: a daemon failing 43% of its sends. The count was green while the daemon was mostly
    # broken. So name the dominant pattern, but ONLY when it actually dominates: "most common: 2"
    # out of 78 carries the same authority as "148 out of 153" while meaning nothing, and on a
    # Python traceback the most repeated line is always `Traceback (most recent call last):`, which
    # names nothing. Both are noise wearing a lead's clothes, so require a third of the total and
    # drop the useless-by-construction line.
    top=""
    if [ "$errors" -gt 2 ]; then
        cand=$(printf '%s\n' "$righe" \
              | grep -viE '^traceback \(most recent call last\):' \
              | sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9:.,]+//g; s/[0-9]{2}:[0-9]{2}:[0-9]{2}[.,0-9]*//g; s/[0-9a-f]{8,}/<id>/g; s/[0-9]+/N/g; s/^[^A-Za-z]+//' \
              | cut -c1-90 | sort | uniq -c | sort -rn | head -1 | sed 's/^ *//')
        n=${cand%% *}
        if [ -n "$n" ] && [ "$n" -ge $(( errors / 3 )) ] && [ "$n" -gt 1 ]; then
            top="$cand"
        fi
    fi
    if [ "$errors" -gt 200 ]; then
        bad "$(basename "$log"): $errors error lines in the last 2 days; read it and find the producer${top:+ | most common: $top}"
    else
        ok "$(basename "$log"): $errors error lines in the last 2 days${top:+ | most common: $top}"
    fi
done

# Refused turns: a turn the provider refused logs in=0 out=0 cache_read=0, since nothing ran, while
# a turn that ran and chose silence still reads its cache. That usage line is the one trace every
# refusal leaves, so count those lines rather than the daemon's rate-limit warnings.

# But that line alone over-counts badly: a compaction boundary and a preempted turn also bill
# nothing. Measured here, 13 of 13 reported refusals were innocent (6 compactions, 7 preempts),
# and any agent that compacts or gets interrupted trips it daily, so it was a permanent RED that
# teaches you to skim the one output meant to stop you skimming. So the zero-usage line is
# necessary and not sufficient: a real refusal has NEITHER marker in the preceding lines.

# Beware when testing this: writing a fake usage line as a fixture gets the command echoed into
# vesta.log by the tool-call logger, so the marker lands in the log this probe reads and the
# count comes back 1. Build fixture markers from runtime-concatenated pieces.
refused=$(grep -h -B4 "$today .*\[USAGE\] in=0 out=0 cache_read=0 " "$HOME"/agent/logs/vesta.log* 2>/dev/null \
    | awk '
        /Compaction boundary reached/ { innocente = 1 }
        /Preempt sent/                { innocente = 1 }
        /\[USAGE\] in=0 out=0 cache_read=0 / { if (!innocente) n++; innocente = 0 }
        /^--$/                        { innocente = 0 }
        END { print n + 0 }')
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

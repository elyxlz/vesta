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
# Overridable for the same reason as the pressure paths below: the timeout branch is unreachable in
# a test otherwise, since it needs a walk that genuinely exceeds two minutes to happen on cue.
DU_TIMEOUT_SECS="${DU_TIMEOUT_SECS:-120}"
# Above this much IO stall (cgroup io.pressure `some avg60`, the percent of the last minute with at
# least one task blocked on disk) a slow filesystem walk is the host starving us, not a local fault.
# A quiet window sits near 1 and a saturated one near 50, so 20 separates them with room either way.
IO_STALL_PERCENT=20
# Overridable so both branches can be exercised. Without this the only reading available is the real
# one, so which branch fires depends on how busy the host happens to be and the other branch can
# never be proven at all. That is how a checker gets shipped half-tested.
IO_PRESSURE_FILE="${IO_PRESSURE_FILE:-/sys/fs/cgroup/io.pressure}"
CPU_PRESSURE_FILE="${CPU_PRESSURE_FILE:-/sys/fs/cgroup/cpu.pressure}"

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
    # A timed-out walk has two causes that call for opposite responses, and one file read separates
    # them rather than guessing. High IO stall alone means the walk was starved by the host's disk,
    # which is external and no amount of cleanup here moves it; cpu_stall is read and reported
    # alongside for context but is not part of this decision, so this does not distinguish a busy
    # host from a box that is also burning local CPU. Low IO stall with a walk that still could not
    # finish in ${DU_TIMEOUT_SECS}s means something is wrong locally.
    io_stall=$(awk '/^some/ {for (i = 1; i <= NF; i++) if ($i ~ /^avg60=/) {sub("avg60=", "", $i); print int($i); exit}}' \
        "$IO_PRESSURE_FILE" 2>/dev/null)
    cpu_stall=$(awk '/^some/ {for (i = 1; i <= NF; i++) if ($i ~ /^avg60=/) {sub("avg60=", "", $i); print int($i); exit}}' \
        "$CPU_PRESSURE_FILE" 2>/dev/null)
    if [ -n "$io_stall" ] && [ "$io_stall" -ge "$IO_STALL_PERCENT" ]; then
        # Deliberately not a RED: it recurs whenever the host is busy, and a nightly RED nobody can
        # act on is how a real RED stops being read. A loud line carrying its evidence instead.
        ok "sizing \$HOME and /tmp exceeded ${DU_TIMEOUT_SECS}s, so the footprint is UNMEASURED, and the cause is external: io.pressure some avg60=${io_stall}% with cpu.pressure ${cpu_stall:-?}%, so the walk was starved by the host's disk rather than by anything here. Nothing to clean up on this line."
    elif [ -z "$io_stall" ]; then
        # An unreadable reading is not a low one, and "IO is NOT stalled" here would assert the one
        # thing that could not be measured. Still a RED, but one that names which case it is.
        bad "sizing \$HOME and /tmp took over ${DU_TIMEOUT_SECS}s and I could NOT read $IO_PRESSURE_FILE, so I cannot tell a starved walk from a pathological tree; investigate tonight"
    else
        bad "sizing \$HOME and /tmp took over ${DU_TIMEOUT_SECS}s while IO was NOT stalled (io.pressure some avg60=${io_stall}%), so this is local: the tree is enormous or a filesystem is stuck; investigate tonight"
    fi
elif [ "${mine:-0}" -ge "$OWN_USAGE_RED_MB" ]; then
    bad "this agent is using ${mine}MB across \$HOME and /tmp: clean up tonight (workspace cleanup)"
elif [ "${usage:-0}" -ge "$HOST_DISK_NOTE_PERCENT" ]; then
    ok "disk at ${usage}% but only ${mine}MB is this agent's; the rest is the host, not yours to clear"
else
    ok "disk at ${usage:-unknown}%, ${mine}MB of it this agent's"
fi

# Error storms: a component can log thousands of errors without one of them reaching a notification.
for log in "$HOME"/agent/logs/*.log; do
    [ -e "$log" ] || continue
    [ -n "$(find "$log" -mmin -1440 2>/dev/null)" ] || continue
    errors=$(tail -n 2000 "$log" | grep -icE 'error|traceback')
    if [ "$errors" -gt 200 ]; then
        bad "$(basename "$log"): $errors error lines in its recent tail; read it and find the producer"
    else
        ok "$(basename "$log"): $errors error lines in its recent tail"
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

if [ "$red" -gt 0 ]; then
    printf '%s RED: fix each tonight or write the reason off in the summary.\n' "$red"
    exit 1
fi
printf 'all probes green\n'
exit 0

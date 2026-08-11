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
for log in "$HOME"/agent/logs/*.log; do
    [ -e "$log" ] || continue
    [ -n "$(find "$log" -mmin -1440 2>/dev/null)" ] || continue
    # A healthy summary line such as "45 matching, 0 new, 0 error(s)" carries the word without
    # reporting a failure, so drop lines whose error or warning count is zero before counting.
    errors=$(tail -n 2000 "$log" \
        | grep -ivE '(^|[^0-9])0 (error|warning)s?\(?s?\)?|no errors' \
        | grep -icE 'error|traceback')
    if [ "$errors" -gt 200 ]; then
        bad "$(basename "$log"): $errors error lines in its recent tail; read it and find the producer"
    else
        ok "$(basename "$log"): $errors error lines in its recent tail"
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

if [ "$red" -gt 0 ]; then
    printf '%s RED: fix each tonight or write the reason off in the summary.\n' "$red"
    exit 1
fi
printf 'all probes green\n'
exit 0

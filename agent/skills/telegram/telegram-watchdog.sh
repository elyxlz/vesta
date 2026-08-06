#!/usr/bin/env bash
# telegram-watchdog: keep the telegram daemon alive. Telegram is often the only live channel to
# the user, so a dead daemon means total silence. This runs detached from the agent, so it heals
# the channel even while the agent is crashed, busy, or mid-restart. Rate-limited so a
# persistently failing daemon backs off instead of hot-looping, and it drops a notification
# whenever it acts.
#
# `telegram daemon start` owns this process: it launches it, records its pid, and
# `telegram daemon stop` ends it before stopping the daemon. Restarting goes through the same
# verb, so the watchdog can only ever bring up the daemon that lifecycle would.
set -u

LAUNCHER="$HOME/agent/skills/telegram/telegram"
PIDFILE="$HOME/agent/data/daemons/telegram.pid"
STAMPS="$HOME/agent/data/telegram-watchdog.stamps"
NOTIF_DIR="${TG_NOTIF_DIR:-$HOME/agent/notifications}"
INTERVAL="${TG_WATCHDOG_INTERVAL:-30}"
WINDOW=300           # rolling window (s) for the restart-rate check
MAX_IN_WINDOW=5      # restarts allowed per WINDOW before backing off
BACKOFF=600          # cooldown (s) once the rate cap is hit

mkdir -p "$(dirname "$STAMPS")"

now() { date +%s; }

daemon_alive() {
  local record pid
  record="$(cat "$PIDFILE" 2>/dev/null)" || return 1
  # The record is "<pid> <starttime>", so the pid is its first field. Passing the whole record to
  # kill would fail on a healthy daemon and restart it on every tick.
  pid="${record%% *}"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# The notifications dir goes with it, so a daemon this brings back writes where the watchdog's
# own notifications go.
start_daemon() { "$LAUNCHER" daemon start --notifications-dir "$NOTIF_DIR" >/dev/null 2>&1; }

notify_restart() { # $1 = note
  local f
  f="$NOTIF_DIR/$(date +%s%N)-telegram-watchdog.json"
  mkdir -p "$NOTIF_DIR"
  printf '{"timestamp":"%s","source":"telegram-watchdog","type":"daemon_restarted","note":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" > "$f"
}

# rolling-rate check using a small timestamp file; echoes 1 if ok to restart, 0 if backing off
rate_ok() {
  local t cutoff count=0 kept=""
  t="$(now)"; cutoff=$((t - WINDOW))
  if [ -f "$STAMPS" ]; then
    for s in $(cat "$STAMPS"); do
      if [ "$s" -ge "$cutoff" ]; then kept="$kept $s"; count=$((count+1)); fi
    done
  fi
  if [ "$count" -ge "$MAX_IN_WINDOW" ]; then echo 0; else echo 1; fi
  echo "$kept $t" | tr -s ' ' > "$STAMPS"
}

echo "telegram-watchdog started (interval=${INTERVAL}s, cap ${MAX_IN_WINDOW}/${WINDOW}s)"
BACKOFF_UNTIL=0

# The wait comes first: `telegram daemon start` launches this only once the daemon is up, so the
# first check worth making is one interval later, and checking on the spot would race a stop.
while true; do
  sleep "$INTERVAL"
  if ! daemon_alive; then
    t="$(now)"
    if [ "$t" -ge "$BACKOFF_UNTIL" ]; then
      ok="$(rate_ok | head -1)"
      start_daemon
      if daemon_alive; then
        notify_restart "auto-restarted after it went down"
        echo "$(date -u +%H:%M:%S) restarted telegram"
      fi
      if [ "$ok" = "0" ]; then
        BACKOFF_UNTIL=$((t + BACKOFF))
        notify_restart "restarting too often, backing off ${BACKOFF}s, needs a look"
        echo "$(date -u +%H:%M:%S) telegram hit rate cap, backing off"
      fi
    fi
  fi
done

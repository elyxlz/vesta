#!/usr/bin/env bash
# telegram-watchdog: keep the telegram daemon alive. With WhatsApp down/unpaired
# (Jun24), Telegram is the sole live channel to the user, so a dead telegram
# daemon = total silence. This runs in its own screen session, independent of the
# agent process, so it heals even while the agent is crashed, busy, or mid-restart
# (the gap that left telegram dead 3x during the Jun24 recovery: daemon died under
# resource pressure, agent was busy, nothing restarted it).
#
# Detects death by process presence (a serve process that exits also ends its
# screen session). Rate-limited so a persistently-failing daemon backs off
# instead of hot-looping, and drops a notification so the agent can tell the user.
set -u

NOTIF_DIR="${TG_NOTIF_DIR:-$HOME/agent/notifications}"
INTERVAL="${TG_WATCHDOG_INTERVAL:-30}"
WINDOW=300           # rolling window (s) for the restart-rate check
MAX_IN_WINDOW=5      # restarts allowed per WINDOW before backing off
BACKOFF=600          # cooldown (s) once the rate cap is hit
COUNTER_DIR="/tmp/tg_watchdog"
mkdir -p "$COUNTER_DIR"

now() { date +%s; }

serve_alive() { pgrep -f "telegram serve --notifications-dir" >/dev/null 2>&1; }

start_daemon() { screen -dmS telegram telegram serve --notifications-dir "$NOTIF_DIR"; }

notify_restart() { # $1 = note
  local f="$NOTIF_DIR/$(date +%s%N)-telegram-watchdog.json"
  mkdir -p "$NOTIF_DIR"
  printf '{"timestamp":"%s","source":"telegram-watchdog","type":"daemon_restarted","note":"%s","interrupt":false}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" > "$f"
}

# rolling-rate check using a small timestamp file; echoes 1 if ok to restart, 0 if backing off
rate_ok() {
  local file="$COUNTER_DIR/telegram.stamps" t cutoff count=0 kept=""
  t="$(now)"; cutoff=$((t - WINDOW))
  if [ -f "$file" ]; then
    for s in $(cat "$file"); do
      if [ "$s" -ge "$cutoff" ]; then kept="$kept $s"; count=$((count+1)); fi
    done
  fi
  if [ "$count" -ge "$MAX_IN_WINDOW" ]; then echo 0; else echo 1; fi
  echo "$kept $t" | tr -s ' ' > "$file"
}

echo "telegram-watchdog started (interval=${INTERVAL}s, cap ${MAX_IN_WINDOW}/${WINDOW}s)"
BACKOFF_UNTIL=0

while true; do
  if ! serve_alive; then
    t="$(now)"
    if [ "$t" -ge "$BACKOFF_UNTIL" ]; then
      ok="$(rate_ok | head -1)"
      start_daemon
      sleep 6
      if serve_alive; then
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
  sleep "$INTERVAL"
done

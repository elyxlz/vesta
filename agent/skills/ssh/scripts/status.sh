#!/usr/bin/env bash
set -euo pipefail

BORE_LOG="/tmp/bore-ssh.log"
BORE_SCREEN="bore-ssh"
SSHD_PID="/tmp/vesta-sshd.pid"

sshd_running() { [ -f "$SSHD_PID" ] && kill -0 "$(cat "$SSHD_PID")" 2>/dev/null; }
bore_running() { screen -ls 2>/dev/null | grep -q "$BORE_SCREEN"; }

if ! sshd_running && ! bore_running; then
    echo "SSH tunnel is not running. Start it with:"
    echo "  ~/vesta/skills/ssh/scripts/start.sh '<public key>'"
    exit 0
fi

echo "sshd: $(sshd_running && echo running || echo stopped)"
echo "bore: $(bore_running && echo running || echo stopped)"

if bore_running; then
    PORT=$(grep -oP 'bore\.pub:\K[0-9]+' "$BORE_LOG" 2>/dev/null || true)
    if [ -n "$PORT" ]; then
        echo ""
        echo "Connect from another machine:"
        echo "  ssh -o StrictHostKeyChecking=accept-new root@bore.pub -p $PORT"
    fi
fi

echo ""
echo "Authorized keys:"
awk '{print "  " $1 " ... " $NF}' /root/.ssh/authorized_keys 2>/dev/null || true

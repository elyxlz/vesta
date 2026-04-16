#!/usr/bin/env bash
set -euo pipefail

BORE_SCREEN="bore-ssh"
SSHD_PID="/tmp/vesta-sshd.pid"
SSHD_PORT_FILE="/tmp/vesta-sshd.port"

if screen -S "$BORE_SCREEN" -X quit 2>/dev/null; then
    echo "Bore tunnel stopped."
else
    echo "No active bore tunnel found."
fi

if [ -f "$SSHD_PID" ]; then
    kill "$(cat "$SSHD_PID")" 2>/dev/null && echo "sshd stopped." || echo "No active sshd found."
    rm -f "$SSHD_PID" "$SSHD_PORT_FILE"
else
    echo "No active sshd found."
fi

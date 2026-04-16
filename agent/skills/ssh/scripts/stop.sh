#!/usr/bin/env bash
BORE_SCREEN="bore-ssh"
SSHD_PID="/tmp/vesta-sshd.pid"

if screen -S "$BORE_SCREEN" -X quit 2>/dev/null; then
    echo "Bore tunnel stopped."
else
    echo "No active bore tunnel found."
fi

if [ -f "$SSHD_PID" ] && kill -0 "$(cat "$SSHD_PID")" 2>/dev/null; then
    kill "$(cat "$SSHD_PID")"
    echo "sshd stopped."
else
    echo "No active sshd found."
fi

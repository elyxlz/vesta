#!/usr/bin/env bash
SCREEN_NAME="bore-ssh"

if screen -S "$SCREEN_NAME" -X quit 2>/dev/null; then
    echo "SSH tunnel stopped."
else
    echo "No active SSH tunnel found."
fi

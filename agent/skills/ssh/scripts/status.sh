#!/usr/bin/env bash
LOG_FILE="/tmp/bore-ssh.log"
SCREEN_NAME="bore-ssh"

if ! screen -ls | grep -q "$SCREEN_NAME"; then
    echo "SSH tunnel is not running. Start it with: ~/vesta/skills/ssh/scripts/start.sh"
    exit 0
fi

PORT=$(grep -oP 'bore\.pub:\K[0-9]+' "$LOG_FILE" 2>/dev/null || true)
if [ -z "$PORT" ]; then
    echo "Tunnel is starting up, no port yet."
    exit 0
fi

USER=$(whoami)
echo "SSH tunnel is running."
echo ""
echo "Connect from another machine:"
echo "  ssh ${USER}@bore.pub -p ${PORT}"

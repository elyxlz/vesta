#!/usr/bin/env bash
BORE_LOG="/tmp/bore-ssh.log"
BORE_SCREEN="bore-ssh"
SSHD_PID="/tmp/vesta-sshd.pid"

SSHD_RUNNING=false
BORE_RUNNING=false

if [ -f "$SSHD_PID" ] && kill -0 "$(cat "$SSHD_PID")" 2>/dev/null; then
    SSHD_RUNNING=true
fi

if screen -ls | grep -q "$BORE_SCREEN"; then
    BORE_RUNNING=true
fi

if ! $SSHD_RUNNING && ! $BORE_RUNNING; then
    echo "SSH tunnel is not running. Start it with:"
    echo "  ~/vesta/skills/ssh/scripts/start.sh '<public key>'"
    exit 0
fi

echo "sshd: $($SSHD_RUNNING && echo running || echo stopped)"
echo "bore: $($BORE_RUNNING && echo running || echo stopped)"

if $BORE_RUNNING; then
    PORT=$(grep -oP 'bore\.pub:\K[0-9]+' "$BORE_LOG" 2>/dev/null || true)
    if [ -n "$PORT" ]; then
        echo ""
        echo "Connect from another machine:"
        echo "  ssh -o StrictHostKeyChecking=accept-new root@bore.pub -p $PORT"
    fi
fi

echo ""
echo "Authorized keys:"
cat /root/.ssh/authorized_keys 2>/dev/null | while read -r line; do
    # Print just the type and comment (first and last fields), not the key body
    TYPE=$(echo "$line" | awk '{print $1}')
    COMMENT=$(echo "$line" | awk '{print $NF}')
    echo "  $TYPE ... $COMMENT"
done

#!/bin/bash

# WhatsApp Bridge Startup Script for Vesta

BRIDGE_DIR="$(dirname "$0")/mcps/whatsapp-mcp/whatsapp-bridge"
NOTIFICATIONS_DIR="$(dirname "$0")/notifications"
LOGS_DIR="$(dirname "$0")/logs"
PIDFILE="/tmp/whatsapp-bridge.pid"

# Create directories if they don't exist
mkdir -p "$NOTIFICATIONS_DIR" "$LOGS_DIR"

# Check if called with --force flag to kill existing bridges
if [ "$1" = "--force" ]; then
    echo "Force mode: Killing all existing WhatsApp bridges..."
    ps aux | grep whatsapp-bridge | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null
    pkill -f whatsapp-bridge 2>/dev/null
    lsof -i :8080 2>/dev/null | grep -v COMMAND | awk '{print $2}' | xargs -r kill -9 2>/dev/null
    rm -f "$PIDFILE"
    sleep 2
else
    # Check if bridge is already running
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "ERROR: WhatsApp bridge already running with PID $PID" >&2
            echo "Multiple bridges will cause connection issues!" >&2
            echo "Use '$0 --force' to kill and restart" >&2
            exit 1
        fi
    fi

    # Also check for any rogue bridges not tracked by PID file
    EXISTING_BRIDGES=$(ps aux | grep whatsapp-bridge | grep -v grep | wc -l)
    if [ "$EXISTING_BRIDGES" -gt 0 ]; then
        echo "ERROR: Found $EXISTING_BRIDGES WhatsApp bridge process(es) already running!" >&2
        echo "Multiple bridges will cause connection issues!" >&2
        echo "Use '$0 --force' to kill and restart" >&2
        exit 1
    fi
fi

# Build bridge if needed
cd "$BRIDGE_DIR"
if [ ! -f "whatsapp-bridge" ]; then
    echo "Building WhatsApp bridge..."
    go build -o whatsapp-bridge .
fi

# Start the bridge with proper environment
echo "Starting WhatsApp bridge..."
NOTIFICATIONS_DIR="$NOTIFICATIONS_DIR" ./whatsapp-bridge \
    >> "$LOGS_DIR/whatsapp-bridge-stdout.log" \
    2>> "$LOGS_DIR/whatsapp-bridge-stderr.log" &

# Save PID
echo $! > "$PIDFILE"
echo "WhatsApp bridge started with PID $(cat $PIDFILE)"
echo "Logs: $LOGS_DIR/whatsapp-bridge-*.log"
echo "Notifications: $NOTIFICATIONS_DIR"
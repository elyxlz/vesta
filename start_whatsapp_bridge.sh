#!/bin/bash

# WhatsApp Bridge Startup Script for Vesta
# Usage: ./start_whatsapp_bridge.sh [--force] [--notifications-dir DIR]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_DIR="$SCRIPT_DIR/mcps/whatsapp-mcp/whatsapp-bridge"
LOGS_DIR="$SCRIPT_DIR/logs"
PIDFILE="/tmp/whatsapp-bridge.pid"

# Parse arguments
FORCE=false
NOTIFICATIONS_DIR="$SCRIPT_DIR/notifications"

while [[ $# -gt 0 ]]; do
    case $1 in
        --force)
            FORCE=true
            shift
            ;;
        --notifications-dir)
            NOTIFICATIONS_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Create directories if they don't exist
mkdir -p "$NOTIFICATIONS_DIR" "$LOGS_DIR"

if [ "$FORCE" = true ]; then
    echo "Force mode: Killing all existing WhatsApp bridges..."
    ps aux | grep whatsapp-bridge | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null
    lsof -i :8080 2>/dev/null | grep -v COMMAND | awk '{print $2}' | xargs -r kill -9 2>/dev/null
    rm -f "$PIDFILE"
    sleep 2
else
    # Check if bridge is already running
    EXISTING_BRIDGES=$(ps aux | grep whatsapp-bridge | grep -v grep | wc -l)
    if [ "$EXISTING_BRIDGES" -gt 0 ]; then
        echo "ERROR: Found $EXISTING_BRIDGES WhatsApp bridge process(es) already running!" >&2
        echo "Use '$0 --force' to kill and restart" >&2
        exit 1
    fi
fi

# Build bridge if needed or if binary is incompatible
cd "$BRIDGE_DIR"
BUILD_NEEDED=false

if [ ! -f "whatsapp-bridge" ]; then
    echo "WhatsApp bridge binary not found, building..."
    BUILD_NEEDED=true
else
    # Test if the binary can execute on this architecture
    ./whatsapp-bridge --help >/dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "WhatsApp bridge binary incompatible with this architecture, rebuilding..."
        rm -f whatsapp-bridge
        BUILD_NEEDED=true
    fi
fi

if [ "$BUILD_NEEDED" = true ]; then
    echo "Building WhatsApp bridge for $(uname -m) architecture..."
    go build -o whatsapp-bridge .
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to build WhatsApp bridge" >&2
        exit 1
    fi
    echo "Build successful!"
fi

# Start the bridge with notifications directory as argument
echo "Starting WhatsApp bridge..."
./whatsapp-bridge --notifications-dir "$NOTIFICATIONS_DIR" \
    >> "$LOGS_DIR/whatsapp-bridge-stdout.log" \
    2>> "$LOGS_DIR/whatsapp-bridge-stderr.log" &

# Save PID
echo $! > "$PIDFILE"
echo "WhatsApp bridge started with PID $(cat $PIDFILE)"
echo "Logs: $LOGS_DIR/whatsapp-bridge-*.log"
echo "Notifications: $NOTIFICATIONS_DIR"
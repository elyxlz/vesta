#!/usr/bin/env bash
set -euo pipefail

BORE_BIN="$HOME/.local/bin/bore"
SCREEN_NAME="bore-ssh"
LOG_FILE="/tmp/bore-ssh.log"
BORE_VERSION="0.5.1"

# Install bore if missing
if [ ! -x "$BORE_BIN" ]; then
    echo "Installing bore..."
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  TRIPLE="x86_64-unknown-linux-musl" ;;
        aarch64) TRIPLE="aarch64-unknown-linux-musl" ;;
        *)       echo "Unsupported architecture: $ARCH"; exit 1 ;;
    esac
    URL="https://github.com/ekzhang/bore/releases/download/v${BORE_VERSION}/bore-v${BORE_VERSION}-${TRIPLE}.tar.gz"
    mkdir -p "$HOME/.local/bin"
    curl -fsSL "$URL" | tar -xz -C "$HOME/.local/bin" bore
    chmod +x "$BORE_BIN"
    echo "bore installed."
fi

# Stop any existing session
screen -S "$SCREEN_NAME" -X quit 2>/dev/null || true

# Start bore in background
screen -dmS "$SCREEN_NAME" bash -c "$BORE_BIN local 22 --to bore.pub > $LOG_FILE 2>&1"

# Wait for bore to print the listening port (up to 10s)
for i in $(seq 1 20); do
    PORT=$(grep -oP 'bore\.pub:\K[0-9]+' "$LOG_FILE" 2>/dev/null || true)
    if [ -n "$PORT" ]; then
        break
    fi
    sleep 0.5
done

if [ -z "$PORT" ]; then
    echo "ERROR: bore failed to start. Log:"
    cat "$LOG_FILE"
    exit 1
fi

USER=$(whoami)
echo "SSH tunnel active."
echo ""
echo "Connect from another machine:"
echo "  ssh ${USER}@bore.pub -p ${PORT}"

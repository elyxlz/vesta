#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLI_DIR="$(dirname "$SCRIPT_DIR")"

# Build Linux CLI
echo "building linux CLI..."
cd "$CLI_DIR"
cargo build --release --target x86_64-unknown-linux-gnu
cp target/x86_64-unknown-linux-gnu/release/vesta "$SCRIPT_DIR/vesta"

# Build VM image
echo "building VM image..."
docker build -t vesta-vm -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"

# Export as rootfs tarball
echo "exporting rootfs..."
CONTAINER=$(docker create vesta-vm)
docker export "$CONTAINER" | gzip > "$SCRIPT_DIR/vesta-wsl-rootfs.tar.gz"
docker rm "$CONTAINER" > /dev/null

# Clean up
rm -f "$SCRIPT_DIR/vesta"

echo "done: $SCRIPT_DIR/vesta-wsl-rootfs.tar.gz"

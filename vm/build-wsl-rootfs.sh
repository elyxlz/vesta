#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Build vestad
echo "building vestad..."
cd "$REPO_DIR"
cargo build --release --target x86_64-unknown-linux-gnu -p vestad
cp target/x86_64-unknown-linux-gnu/release/vestad "$SCRIPT_DIR/vestad"

# Build WSL image (with NVIDIA toolkit for GPU passthrough)
echo "building WSL image..."
docker build --build-arg INCLUDE_NVIDIA=true -t vesta-wsl -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"

# Export as rootfs tarball
echo "exporting rootfs..."
CONTAINER=$(docker create vesta-wsl)
docker export "$CONTAINER" | gzip > "$SCRIPT_DIR/vesta-wsl-rootfs.tar.gz"
docker rm "$CONTAINER" > /dev/null

# Clean up
rm -f "$SCRIPT_DIR/vestad"

echo "done: $SCRIPT_DIR/vesta-wsl-rootfs.tar.gz"

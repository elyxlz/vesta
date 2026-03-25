#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARCH="${1:-$(dpkg --print-architecture 2>/dev/null || echo amd64)}"
OUTPUT_DIR="${2:-$SCRIPT_DIR}"

echo "building VM image for $ARCH..."

# Build the Docker image (with kernel for VM boot)
docker build --platform "linux/$ARCH" --build-arg INCLUDE_KERNEL=true -t vesta-vm -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"

# Export rootfs
echo "exporting rootfs..."
CONTAINER=$(docker create --platform "linux/$ARCH" vesta-vm)
docker export "$CONTAINER" > /tmp/vesta-rootfs.tar
docker rm "$CONTAINER" > /dev/null

# Create disk image (20GB sparse, ext4)
echo "creating disk image..."
DISK="/tmp/vesta-vm-disk.raw"
truncate -s 20G "$DISK"
mkfs.ext4 -q "$DISK"

# Mount and populate
MOUNT_DIR=$(mktemp -d)
sudo mount "$DISK" "$MOUNT_DIR"
sudo tar -xf /tmp/vesta-rootfs.tar -C "$MOUNT_DIR"

# Extract kernel + initrd (symlinked to vmlinuz-virt / initramfs-virt in Dockerfile)
VMLINUZ="$MOUNT_DIR/boot/vmlinuz-virt"
INITRD="$MOUNT_DIR/boot/initramfs-virt"
if [ ! -f "$VMLINUZ" ] || [ ! -f "$INITRD" ]; then
    sudo umount "$MOUNT_DIR"
    rmdir "$MOUNT_DIR"
    echo "error: kernel or initrd not found in image"
    exit 1
fi

# ARM64 requires uncompressed kernel for Virtualization.framework
if [ "$ARCH" = "arm64" ]; then
    echo "decompressing kernel for arm64..."
    # ARM64: vfkit needs an uncompressed kernel Image.
    # Debian ARM64 vmlinuz may be uncompressed already or gzip-wrapped in an EFI stub.
    python3 -c "
import zlib, shutil
with open('$VMLINUZ', 'rb') as f:
    data = f.read()
off = 0
while True:
    off = data.find(b'\x1f\x8b\x08', off)
    if off < 0:
        break
    try:
        raw = zlib.decompressobj(zlib.MAX_WBITS | 16).decompress(data[off:])
        if len(raw) > 1024 * 1024:
            with open('$OUTPUT_DIR/vm-kernel', 'wb') as f:
                f.write(raw)
            print(f'decompressed kernel: {len(raw)} bytes (gzip at offset {off})')
            raise SystemExit(0)
    except zlib.error:
        pass
    off += 1
shutil.copy('$VMLINUZ', '$OUTPUT_DIR/vm-kernel')
print('kernel is already uncompressed')
"
else
    cp "$VMLINUZ" "$OUTPUT_DIR/vm-kernel"
fi
cp "$INITRD" "$OUTPUT_DIR/vm-initrd"

sudo umount "$MOUNT_DIR"
rmdir "$MOUNT_DIR"
rm /tmp/vesta-rootfs.tar

mv "$DISK" "$OUTPUT_DIR/vm-disk.raw"

# Package
echo "packaging..."
cd "$OUTPUT_DIR"
tar --zstd -cf "vesta-vm-${ARCH}.tar.zst" vm-kernel vm-initrd vm-disk.raw
rm -f vm-kernel vm-initrd vm-disk.raw

echo "done: $OUTPUT_DIR/vesta-vm-${ARCH}.tar.zst"

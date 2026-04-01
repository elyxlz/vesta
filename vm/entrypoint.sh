#!/bin/sh
set -eu

# Remount root read-write (initramfs may mount it read-only)
mount -o remount,rw / 2>/dev/null || true

# Mount essential virtual filesystems (skip if already mounted, e.g. WSL2)
mountpoint -q /proc    || mount -t proc proc /proc
mountpoint -q /sys     || mount -t sysfs sysfs /sys
mountpoint -q /dev     || mount -t devtmpfs devtmpfs /dev
mkdir -p /dev/pts /dev/shm
mountpoint -q /dev/pts || mount -t devpts devpts /dev/pts
mountpoint -q /dev/shm || mount -t tmpfs tmpfs /dev/shm
mountpoint -q /tmp     || mount -t tmpfs tmpfs /tmp
mountpoint -q /run     || mount -t tmpfs tmpfs /run

# Bring up loopback interface (needed for localhost/127.0.0.1)
ip link set lo up 2>/dev/null || true

# Configure network (DHCP on first ethernet interface, needed for internet in VM)
# Runs in background so it doesn't block SSH (which is over vsock, not network)
for iface in /sys/class/net/eth*; do
    [ -e "$iface" ] || continue
    iface_name="$(basename "$iface")"
    ip link set "$iface_name" up 2>/dev/null || true
    dhclient -1 "$iface_name" 2>/dev/null || true &
done

# Mount cgroup v2 (unified hierarchy)
mkdir -p /sys/fs/cgroup
mountpoint -q /sys/fs/cgroup || mount -t cgroup2 cgroup2 /sys/fs/cgroup

# Enable cgroup nesting so dockerd can create child cgroups
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
    mkdir -p /sys/fs/cgroup/init
    xargs -rn1 < /sys/fs/cgroup/cgroup.procs > /sys/fs/cgroup/init/cgroup.procs 2>/dev/null || true
    sed -e 's/ / +/g' -e 's/^/+/' < /sys/fs/cgroup/cgroup.controllers \
        > /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null || true
fi

# Shared mount propagation (required for container mount namespaces)
mount --make-rshared /

# SSH keys from host (vfkit virtio-fs, macOS only)
mkdir -p /mnt/ssh-keys
mount -t virtiofs ssh-keys /mnt/ssh-keys 2>/dev/null || true
if [ -f /mnt/ssh-keys/authorized_keys ]; then
    cp /mnt/ssh-keys/authorized_keys /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
fi

# Use iptables-legacy (WSL2 kernel lacks full nftables support)
if [ -x /sbin/iptables-legacy ] && [ -x /sbin/ip6tables-legacy ] \
   && iptables --version 2>/dev/null | grep -q nf_tables; then
    ln -sf /sbin/iptables-legacy /sbin/iptables
    ln -sf /sbin/ip6tables-legacy /sbin/ip6tables
fi

# Start NTP (handles clock drift after host sleep/wake)
chronyd 2>/dev/null || true

# Configure NVIDIA container runtime if toolkit is installed
if command -v nvidia-ctk >/dev/null 2>&1; then
    nvidia-ctk runtime configure --runtime=docker 2>/dev/null || true
fi

# Start Docker
rm -f /var/run/docker.pid /var/run/containerd/containerd.pid
dockerd --storage-driver=overlay2 &>/dev/null &
i=0
while [ ! -S /var/run/docker.sock ]; do
    i=$((i+1))
    if [ "$i" -gt 120 ]; then echo "dockerd failed to start" >&2; exit 1; fi
    sleep 0.5
done
# Wait for dockerd to actually accept connections (socket can exist before ready)
i=0
while ! docker info >/dev/null 2>&1; do
    i=$((i+1))
    if [ "$i" -gt 60 ]; then echo "dockerd not responding" >&2; exit 1; fi
    sleep 0.5
done

# Start SSH (daemon mode, -e logs to stderr)
/usr/sbin/sshd -D -e &

# Start vestad API server
vestad serve &

# Bridge vsock port 2222 to SSH (macOS vfkit only, silently skipped on WSL2)
# Load virtio vsock transport (creates /dev/vsock); silently skip if not available
modprobe vmw_vsock_virtio_transport 2>/dev/null || true
if [ -e /dev/vsock ]; then
    socat VSOCK-LISTEN:2222,reuseaddr,fork TCP4:127.0.0.1:22 &
fi

# Keep PID 1 alive; forward SIGTERM for clean shutdown
trap 'kill 0; exit 0' TERM INT
wait

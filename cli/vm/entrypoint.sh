#!/bin/sh
set -eu

# Mount essential virtual filesystems (kernel mounts nothing automatically)
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /dev/pts /dev/shm
mount -t devpts devpts /dev/pts
mount -t tmpfs tmpfs /dev/shm
mount -t tmpfs tmpfs /tmp
mount -t tmpfs tmpfs /run

# Mount cgroup v2 (unified hierarchy)
mkdir -p /sys/fs/cgroup
mount -t cgroup2 cgroup2 /sys/fs/cgroup

# Enable cgroup nesting so dockerd can create child cgroups
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
    mkdir -p /sys/fs/cgroup/init
    xargs -rn1 < /sys/fs/cgroup/cgroup.procs > /sys/fs/cgroup/init/cgroup.procs 2>/dev/null || true
    sed -e 's/ / +/g' -e 's/^/+/' < /sys/fs/cgroup/cgroup.controllers \
        > /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null || true
fi

# Shared mount propagation (required for container mount namespaces)
mount --make-rshared /

# SSH keys from host (vfkit virtio-fs)
mkdir -p /mnt/ssh-keys
mount -t virtiofs ssh-keys /mnt/ssh-keys 2>/dev/null || true
if [ -f /mnt/ssh-keys/authorized_keys ]; then
    cp /mnt/ssh-keys/authorized_keys /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
fi

# Start Docker
rm -f /var/run/docker.pid /var/run/containerd/containerd.pid
dockerd --storage-driver=overlay2 &>/dev/null &
while [ ! -S /var/run/docker.sock ]; do sleep 0.5; done

# Start SSH (foreground)
exec /usr/sbin/sshd -D -e

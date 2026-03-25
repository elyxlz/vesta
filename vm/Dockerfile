FROM debian:bookworm-slim

ARG INCLUDE_KERNEL=false
ARG INCLUDE_NVIDIA=false

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
        openssh-server \
        docker.io iptables \
        iproute2 kmod socat chrony \
        isc-dhcp-client \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* \
    && rm -rf /usr/share/doc /usr/share/man /usr/share/locale

# Linux kernel for VM boot (macOS vfkit only)
RUN if [ "$INCLUDE_KERNEL" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends \
            linux-image-cloud-$(dpkg --print-architecture) \
        && rm -rf /var/lib/apt/lists/* /var/cache/apt/* \
        && cd /boot \
        && ln -sf vmlinuz-* vmlinuz-virt \
        && ln -sf initrd.img-* initramfs-virt; \
    fi

# NVIDIA Container Toolkit for GPU passthrough (WSL2 / Linux server)
RUN if [ "$INCLUDE_NVIDIA" = "true" ]; then \
        mkdir -p /etc/apt/keyrings \
        && curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
            > /etc/apt/keyrings/nvidia-container-toolkit.asc \
        && curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
            | sed 's#deb https://#deb [signed-by=/etc/apt/keyrings/nvidia-container-toolkit.asc] https://#g' \
            > /etc/apt/sources.list.d/nvidia-container-toolkit.list \
        && apt-get update \
        && apt-get install -y --no-install-recommends nvidia-container-toolkit \
        && rm -rf /var/lib/apt/lists/* /var/cache/apt/* \
        && nvidia-ctk runtime configure --runtime=docker; \
    fi

# SSH
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh \
    && ssh-keygen -A \
    && sed -i 's/#PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config

# Vesta server daemon
COPY vestad /usr/local/bin/vestad
RUN chmod +x /usr/local/bin/vestad

# Boot
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# WSL boot config (only used when imported as WSL distro)
COPY wsl.conf /etc/wsl.conf

CMD ["/entrypoint.sh"]

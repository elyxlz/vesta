FROM alpine:3.21

RUN echo "https://dl-cdn.alpinelinux.org/alpine/v3.21/community" >> /etc/apk/repositories

RUN apk add --no-cache \
    ca-certificates curl openssh docker containerd iptables gcompat

# Kernel optimized for VMs (virtio drivers built-in, not modules)
RUN apk add --no-cache linux-virt

# SSH
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh \
    && ssh-keygen -A \
    && sed -i 's/#PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config

# Vesta CLI
COPY vesta /usr/local/bin/vesta
RUN chmod +x /usr/local/bin/vesta

# Boot
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# WSL boot config (only used when imported as WSL distro)
COPY wsl.conf /etc/wsl.conf

CMD ["/entrypoint.sh"]

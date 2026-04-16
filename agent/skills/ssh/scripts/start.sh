#!/usr/bin/env bash
set -euo pipefail

BORE_BIN="$HOME/.local/bin/bore"
BORE_VERSION="0.5.1"
BORE_LOG="/tmp/vesta-bore-ssh.log"
BORE_SCREEN="bore-ssh"
SSHD_PID="/tmp/vesta-sshd.pid"
SSHD_PORT_FILE="/tmp/vesta-sshd.port"
SSHD_CONFIG="/tmp/vesta-sshd.conf"

if [ -z "${1:-}" ]; then
    echo "ERROR: public key required."
    echo ""
    echo "On the connecting machine, run:"
    echo "  cat ~/.ssh/id_ed25519.pub"
    echo "  # or: cat ~/.ssh/id_rsa.pub"
    echo "  # no key? generate one: ssh-keygen -t ed25519"
    echo ""
    echo "Then pass the output to this script:"
    echo "  $0 'ssh-ed25519 AAAA... user@host'"
    exit 1
fi

PUBLIC_KEY="$1"

if ! command -v sshd &>/dev/null; then
    echo "Installing openssh-server..."
    apt-get install -y -q openssh-server
fi

ssh-keygen -A -q 2>/dev/null || true

SSHD_PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('',0)); p=s.getsockname()[1]; s.close(); print(p)")
echo "$SSHD_PORT" > "$SSHD_PORT_FILE"

cat > "$SSHD_CONFIG" <<EOF
Port $SSHD_PORT
ListenAddress 0.0.0.0
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile /root/.ssh/authorized_keys
HostKey /etc/ssh/ssh_host_ed25519_key
HostKey /etc/ssh/ssh_host_rsa_key
PidFile $SSHD_PID
EOF

mkdir -p /root/.ssh
chmod 700 /root/.ssh
AUTHKEYS="/root/.ssh/authorized_keys"
if ! grep -qF "$PUBLIC_KEY" "$AUTHKEYS" 2>/dev/null; then
    echo "$PUBLIC_KEY" >> "$AUTHKEYS"
    echo "Public key added."
else
    echo "Public key already authorized."
fi
chmod 600 "$AUTHKEYS"

if [ -f "$SSHD_PID" ]; then
    kill "$(cat "$SSHD_PID")" 2>/dev/null || true
    sleep 0.5
fi
/usr/sbin/sshd -f "$SSHD_CONFIG"
echo "sshd running on port $SSHD_PORT."

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

screen -S "$BORE_SCREEN" -X quit 2>/dev/null || true
rm -f "$BORE_LOG"

screen -dmS "$BORE_SCREEN" bash -c "$BORE_BIN local $SSHD_PORT --to bore.pub > $BORE_LOG 2>&1"

PORT=""
for i in $(seq 1 20); do
    PORT=$(grep -oP 'bore\.pub:\K[0-9]+' "$BORE_LOG" 2>/dev/null || true)
    [ -n "$PORT" ] && break
    sleep 0.5
done

if [ -z "$PORT" ]; then
    echo "ERROR: bore failed to get a port. Log:"
    cat "$BORE_LOG"
    exit 1
fi

echo ""
echo "SSH tunnel active. On the connecting machine, run:"
echo ""
echo "  ssh -o StrictHostKeyChecking=accept-new root@bore.pub -p $PORT"
echo ""
echo "If the connecting machine has a different default key, specify it:"
echo "  ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new root@bore.pub -p $PORT"

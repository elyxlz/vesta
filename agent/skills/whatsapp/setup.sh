#!/usr/bin/env bash
# Idempotent whatsapp skill setup. Safe to re-run any time: every step is a
# no-op when already done. The Go toolchain, whisper.cpp static libs, gcc and
# ffmpeg ship in the agent image, nothing is apt-installed or compiled from
# C source here.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. Launcher on PATH (compiles the CLI from source on every invocation).
mkdir -p "$HOME/.local/bin"
ln -sf "$SKILL_DIR/whatsapp" "$HOME/.local/bin/whatsapp"

# 2. Warm the build cache; a compile problem surfaces HERE, loudly, not later.
echo "setup: compiling the whatsapp CLI (first run can take a few minutes)..."
whatsapp --help >/dev/null

# 3. Whisper model for voice-note transcription.
MODEL=/usr/local/share/ggml-small.bin
MODEL_SHA256="1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"
if [ ! -f "$MODEL" ]; then
  echo "setup: downloading whisper model (~470MB)..."
  curl -fSL -o "$MODEL.tmp" https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
  echo "$MODEL_SHA256  $MODEL.tmp" | sha256sum -c -
  mv "$MODEL.tmp" "$MODEL"
fi

# 4. Restart-skill daemon line so the daemon survives container restarts.
RESTART_MD="$HOME/agent/skills/restart/SKILL.md"
DAEMON_LINE='running whatsapp || { whatsapp daemon start; sleep 1; }'
if [ -f "$RESTART_MD" ] && ! grep -qF "$DAEMON_LINE" "$RESTART_MD"; then
  printf '\n```bash\n# whatsapp\n%s\n```\n' "$DAEMON_LINE" >> "$RESTART_MD"
fi

# 5. Start the daemon (idempotent; defaults --notifications-dir to ~/agent/notifications).
whatsapp daemon start

echo "setup complete, link an account with: whatsapp link"

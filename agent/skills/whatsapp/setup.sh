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

# 4. Start the daemon (idempotent; defaults --notifications-dir to ~/agent/notifications).
whatsapp start

echo "setup complete, link an account with: whatsapp link"
echo
echo "Remaining step, yours to do: add this line inside the fenced Daemons block"
echo "of ~/agent/skills/restart/SKILL.md, matching the guard form already there."
echo "\`whatsapp start\` brings the daemon up and waits until it answers, so inbound"
echo "notifications flow before you send anything."
echo '  running whatsapp || { whatsapp start; sleep 1; }'

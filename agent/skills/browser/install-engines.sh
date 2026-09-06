#!/usr/bin/env bash
# Installs the two browser engines the browser daemon drives (Debian's chromium and the pinned
# Camoufox bundle), the display packages every session's own X display needs (xvfb, openbox,
# x11vnc, novnc), and the fonts Chromium renders pages with (fonts-liberation, fonts-dejavu-core,
# fonts-noto-core). Run by the Dockerfile for fresh images and by the browser-daemon migration on
# the fleet (fleet upgrades never rerun the Dockerfile). Safe to rerun.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Every apt package this box lacks, gathered first so one update and one install cover them all.
packages=()
if ! command -v chromium >/dev/null 2>&1; then
  packages+=(chromium)
fi
if ! command -v Xvfb >/dev/null 2>&1 || ! command -v openbox >/dev/null 2>&1 \
  || ! command -v x11vnc >/dev/null 2>&1 || ! command -v websockify >/dev/null 2>&1 \
  || [ ! -f /usr/share/novnc/core/rfb.js ]; then
  packages+=(xvfb openbox x11vnc novnc)
fi
if [ ! -f /usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf ] \
  || [ ! -f /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf ] \
  || [ ! -f /usr/share/fonts/truetype/noto/NotoSans-Regular.ttf ]; then
  packages+=(fonts-liberation fonts-dejavu-core fonts-noto-core)
fi
if [ "${#packages[@]}" -gt 0 ]; then
  apt-get update
  apt-get install -y --no-install-recommends "${packages[@]}"
  rm -rf /var/lib/apt/lists/*
fi

python3 "$SKILL_DIR/cli/src/vesta_browser/camoufox_install.py"

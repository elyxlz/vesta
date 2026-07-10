#!/usr/bin/env bash
# One owner of the whisper.cpp static build. Called by the Dockerfile's
# whisper-build stage and by `check.sh whatsapp`. Builds the go.mod-pinned
# commit into DEST and is a no-op when that pinned build is already present.
set -euo pipefail

CLI_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:?usage: build-whisper.sh <dest-dir>}"

PIN=$(grep 'github.com/ggerganov/whisper.cpp' "$CLI_DIR/go.mod" | head -1 | awk -F'-' '{print $NF}')
if [ -z "$PIN" ]; then
  echo "build-whisper: no whisper.cpp pin found in $CLI_DIR/go.mod" >&2
  exit 1
fi

if [ -f "$DEST/.pin" ] && [ "$(cat "$DEST/.pin")" = "$PIN" ] && [ -f "$DEST/build-static/src/libwhisper.a" ]; then
  echo "build-whisper: pinned build $PIN already present at $DEST"
  exit 0
fi

if [ ! -d "$DEST/.git" ]; then
  git clone https://github.com/ggerganov/whisper.cpp.git "$DEST"
fi
git -C "$DEST" checkout "$PIN" 2>/dev/null || { git -C "$DEST" fetch origin "$PIN" && git -C "$DEST" checkout "$PIN"; }

# GGML_NATIVE=OFF: the image is built on release runners, so the static libs
# must target the baseline ISA, not the builder CPU (SIGILL on lesser boxes).
cmake -B "$DEST/build-static" -S "$DEST" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DGGML_NATIVE=OFF \
  -DGGML_OPENMP=ON
cmake --build "$DEST/build-static" --config Release -j"$(nproc)"
echo "$PIN" > "$DEST/.pin"

# WhatsApp Setup

## 1. Install dependencies

`apt-get update` first if the index is stale (base image often is).

```bash
apt-get update
apt-get install -y gcc g++ cmake ffmpeg
ARCH=$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')
curl -fsSL "https://go.dev/dl/$(curl -fsSL 'https://go.dev/VERSION?m=text' | head -1).linux-${ARCH}.tar.gz" | tar -C /usr/local -xz
export PATH="/usr/local/go/bin:$PATH"
```

`g++` and `cmake` are NOT pulled in by `gcc` alone. Without them the whisper.cpp configure fails silently (cmake) or with `No CMAKE_CXX_COMPILER could be found` (g++).

## 2. Build whisper.cpp (static libraries)

The WhatsApp CLI links whisper.cpp statically via CGO for voice note transcription.

The Go binding under `bindings/go` is pinned to a specific whisper.cpp commit in `cli/go.mod` (look for the `github.com/ggerganov/whisper.cpp` line, e.g. `v0.0.0-YYYYMMDDhhmmss-<short_sha>`). Master is usually ahead and breaks the binding (`undefined: whisper.Params`, etc.). Check out the matching commit before configuring:

```bash
git clone https://github.com/ggerganov/whisper.cpp.git /opt/whisper.cpp
cd /opt/whisper.cpp
PIN=$(grep 'ggerganov/whisper.cpp' ~/agent/skills/whatsapp/cli/go.mod | head -1 | awk -F'-' '{print $NF}')
git checkout "$PIN"

cmake -B build-static -S . \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DGGML_OPENMP=ON
cmake --build build-static --config Release -j$(nproc)
```

## 3. Download a whisper model

Download to `/usr/local/share/`. The CLI tries models in order: `ggml-small.bin`, `ggml-small.en.bin`, `ggml-tiny.bin`, `ggml-tiny.en.bin`. Override with `WHISPER_MODEL` env var.

```bash
curl -fSL -o /usr/local/share/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

## 4. Build the WhatsApp CLI

```bash
cd ~/agent/skills/whatsapp/cli

C_INCLUDE_PATH=/opt/whisper.cpp/include:/opt/whisper.cpp/ggml/include \
LIBRARY_PATH=/opt/whisper.cpp/build-static/src:/opt/whisper.cpp/build-static/ggml/src \
CGO_CFLAGS="-DSQLITE_ENABLE_FTS5" \
CGO_LDFLAGS="-lwhisper -lggml -lggml-base -lggml-cpu -lm -lstdc++ -fopenmp" \
PATH="/usr/local/go/bin:$PATH" \
go build -tags "fts5" -o /usr/local/bin/whatsapp .
```

| Variable | Purpose |
|---|---|
| `C_INCLUDE_PATH` | Points to whisper.cpp and ggml headers |
| `LIBRARY_PATH` | Points to the static `.a` libraries |
| `CGO_CFLAGS` | Enables SQLite FTS5 for message search |
| `CGO_LDFLAGS` | Links whisper, ggml, and C++ runtime |
| `-tags "fts5"` | Activates the FTS5 build tag for go-sqlite3 |

## 5. Start the daemon and authenticate

```bash
screen -dmS whatsapp whatsapp serve --notifications-dir ~/agent/notifications
sleep 3
```

**Before authenticating**, confirm with the user that they should link from a dedicated WhatsApp account for the assistant, NOT their personal WhatsApp. Linking their personal account would mean the assistant reads/sends from their personal chats.

If the user doesn't have a separate number yet, read [PHONE_NUMBER.md](PHONE_NUMBER.md) and guide them through getting a cheap prepaid SIM/eSIM and setting up a second WhatsApp account on their phone.

### QR code (preferred)

QR code is the default and preferred method:

```bash
whatsapp authenticate
```

A QR code image is saved to `~/.whatsapp/qr-code.png`. Upload it to a temporary host:

```bash
curl -sF 'reqtype=fileupload' -F 'time=1h' -F 'fileToUpload=@~/.whatsapp/qr-code.png' https://litterbox.catbox.moe/resources/internals/api.php
```

**QR codes expire in ~20 seconds.** Confirm the user is on the **Linked Devices > Link a Device** screen with the camera ready BEFORE you call `authenticate`. Sequence: ask "ready?" → wait for confirmation → run `authenticate` + upload + send link in a single chained command, no preamble. If they scan and get **"Could not link device, try again later"**, the daemon's WS to whatsapp.com went stale: restart the daemon (see Troubleshooting below) before the next attempt, otherwise every retry fails the same way.

### Phone pairing (fallback)

If QR scanning isn't convenient, use phone pairing instead:

```bash
whatsapp pair-phone --phone '+1234567890'
```

This returns a pairing code (e.g. `4YGP-5174`). Send it to the user and tell them:
WhatsApp > Linked Devices > Link a Device > Link with phone number > enter code.

### After authentication

Check status:

```bash
whatsapp authenticate
```

**NEVER restart the daemon after the user has authenticated.** Restarting can invalidate the session. If `authenticate` still says not authenticated, wait longer and check again (up to 30 seconds). Only restart if the user confirms they didn't complete auth in time.

### Troubleshooting: "Can't link at this time"

If the user scans the QR code but WhatsApp shows **"Can't link at this time"**, the daemon's WebSocket connection is stale. Fully restart the daemon and try again:

```bash
screen -S whatsapp -X quit
sleep 2
screen -dmS whatsapp whatsapp serve --notifications-dir ~/agent/notifications
sleep 3
whatsapp pair-phone --phone '+1234567890'   # or: whatsapp authenticate (for QR)
```

## 6. Register the service

Add to the `## Services` section of `~/agent/skills/restart/SKILL.md`:

```
screen -dmS whatsapp whatsapp serve --notifications-dir ~/agent/notifications
```

## How transcription works

1. When a voice note arrives, the CLI downloads the audio via the WhatsApp media API
2. `ffmpeg` converts the OGG/Opus audio to 16kHz mono WAV
3. The built-in whisper.cpp bindings transcribe the audio to text
4. The transcription replaces the `[audio]` placeholder in the notification

All transcription runs in-process, no external scripts or services needed.

## Contact card support

When someone sends a WhatsApp contact card (vCard), it is parsed and stored as:

```
[Contact: Name - +phonenumber]
```

The phone number is extracted from the `TEL` field of the vCard. Use `list-received-contacts` to list all received contact cards:

```bash
whatsapp list-received-contacts
whatsapp list-received-contacts --to Alex --limit 10
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `/usr/local/share/ggml-small.bin` | Path to the GGML whisper model file |

# WhatsApp Setup

## 1. Install dependencies

```bash
apt-get install -y gcc ffmpeg
ARCH=$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')
curl -fsSL "https://go.dev/dl/$(curl -fsSL 'https://go.dev/VERSION?m=text' | head -1).linux-${ARCH}.tar.gz" | tar -C /usr/local -xz
export PATH="/usr/local/go/bin:$PATH"
```

## 2. Build whisper.cpp (static libraries)

The WhatsApp CLI links whisper.cpp statically via CGO for voice note transcription.

```bash
git clone https://github.com/ggerganov/whisper.cpp.git /opt/whisper.cpp
cd /opt/whisper.cpp

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
cd ~/vesta/skills/whatsapp/cli

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
screen -dmS whatsapp whatsapp serve
sleep 3
whatsapp authenticate
```

**Before showing the QR code**, confirm with the user that they should scan it from a dedicated WhatsApp account for the assistant — NOT their personal WhatsApp. Scanning from their personal account would link their own WhatsApp to Vesta and she'd be reading/sending from their personal chats.

If the user doesn't have a separate number yet, read [PHONE_NUMBER.md](PHONE_NUMBER.md) and guide them through getting a cheap prepaid SIM/eSIM and setting up a second WhatsApp account on their phone.

If not authenticated, a QR code image is saved to `~/vesta/data/whatsapp/qr-code.png`.
Upload it to a temporary hosting service so the user can open it from any device:
```bash
curl -sF 'reqtype=fileupload' -F 'time=1h' -F 'fileToUpload=@~/vesta/data/whatsapp/qr-code.png' https://litterbox.catbox.moe/resources/internals/api.php
```
This returns a URL (e.g. `https://litter.catbox.moe/abc123.png`) that expires in 1 hour. Send the link to the user and tell them to open it and scan immediately.

**QR codes expire in ~20 seconds.** Warn the user to have WhatsApp ready before opening the link.

After the user says they scanned, wait 10 seconds then check:
```bash
sleep 10 && whatsapp authenticate
```
**NEVER restart the daemon after the user has scanned** — restarting invalidates the session. If `authenticate` still says not authenticated, wait longer and check again (up to 30 seconds). Only restart the daemon if the user confirms they didn't scan in time or the QR visually expired.

## 6. Add to restart.md

```
screen -dmS whatsapp whatsapp serve --notifications-dir ~/vesta/notifications
```

## How transcription works

1. When a voice note arrives, the CLI downloads the audio via the WhatsApp media API
2. `ffmpeg` converts the OGG/Opus audio to 16kHz mono WAV
3. The built-in whisper.cpp bindings transcribe the audio to text
4. The transcription replaces the `[audio]` placeholder in the notification

All transcription runs in-process — no external scripts or services needed.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `/usr/local/share/ggml-small.bin` | Path to the GGML whisper model file |

# WhatsApp CLI Setup

The WhatsApp CLI is a standalone Go binary that connects to WhatsApp via whatsmeow and includes built-in voice note transcription via whisper.cpp CGO bindings.

## Prerequisites

- **Go** 1.25+ (installed to `/usr/local/go/bin`)
- **ffmpeg** (for audio format conversion)
- **GCC / C++ toolchain** (for CGO compilation)
- **OpenMP** runtime (`libgomp`)

## Building whisper.cpp (static libraries)

The WhatsApp CLI links whisper.cpp statically via CGO. You must compile whisper.cpp as static libraries first.

```bash
# Clone whisper.cpp
git clone https://github.com/ggerganov/whisper.cpp.git /opt/whisper.cpp
cd /opt/whisper.cpp

# Build static libraries (CPU-only, no GPU needed for server use)
cmake -B build-static -S . \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DGGML_OPENMP=ON
cmake --build build-static --config Release -j$(nproc)
```

After building, the required static libraries will be at:
- `/opt/whisper.cpp/build-static/src/libwhisper.a`
- `/opt/whisper.cpp/build-static/ggml/src/libggml.a`
- `/opt/whisper.cpp/build-static/ggml/src/libggml-base.a`
- `/opt/whisper.cpp/build-static/ggml/src/libggml-cpu.a`

## Downloading a whisper model

Download a whisper model to `/usr/local/share/`. The CLI tries `ggml-small.en.bin` first, then falls back to `ggml-tiny.en.bin`. You can override the path with the `WHISPER_MODEL` environment variable.

```bash
# Option A: small.en (better accuracy, ~466 MB)
curl -L -o /usr/local/share/ggml-small.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin

# Option B: tiny.en (faster, ~75 MB)
curl -L -o /usr/local/share/ggml-tiny.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin
```

## Building the WhatsApp CLI

```bash
cd agent/tools/whatsapp

C_INCLUDE_PATH=/opt/whisper.cpp/include:/opt/whisper.cpp/ggml/include \
LIBRARY_PATH=/opt/whisper.cpp/build-static/src:/opt/whisper.cpp/build-static/ggml/src \
CGO_CFLAGS="-DSQLITE_ENABLE_FTS5" \
CGO_LDFLAGS="-lwhisper -lggml -lggml-base -lggml-cpu -lm -lstdc++ -fopenmp" \
PATH="/usr/local/go/bin:$PATH" \
go build -tags "fts5" -o /usr/local/bin/whatsapp .
```

### Build flags explained

| Variable | Purpose |
|---|---|
| `C_INCLUDE_PATH` | Points to whisper.cpp and ggml headers |
| `LIBRARY_PATH` | Points to the static `.a` libraries |
| `CGO_CFLAGS` | Enables SQLite FTS5 for message search |
| `CGO_LDFLAGS` | Links whisper, ggml, and C++ runtime |
| `-tags "fts5"` | Activates the FTS5 build tag for go-sqlite3 |

## Runtime requirements

- The `whatsapp` binary at `/usr/local/bin/whatsapp`
- `ffmpeg` on PATH (used to convert audio to 16kHz mono WAV before transcription)
- A whisper model file at `/usr/local/share/ggml-small.en.bin` (or `ggml-tiny.en.bin`, or set `WHISPER_MODEL`)

## How transcription works

1. When a voice note arrives, the CLI downloads the audio via the WhatsApp media API
2. `ffmpeg` converts the OGG/Opus audio to 16kHz mono WAV
3. The built-in whisper.cpp bindings transcribe the audio to text
4. The transcription replaces the `[audio]` placeholder in the notification

All transcription runs in-process -- no external scripts or services needed.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `/usr/local/share/ggml-small.en.bin` | Path to the GGML whisper model file |
| `WHATSAPP_DATA_DIR` | `~/.whatsapp` | Directory for WhatsApp session data and message DB |
| `WHATSAPP_NOTIFICATIONS_DIR` | (none) | Directory where notification files are written |

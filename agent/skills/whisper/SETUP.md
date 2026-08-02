# Whisper Setup

```bash
# 1. Install build deps and ffmpeg
apt-get update && apt-get install -y build-essential cmake ffmpeg

# 2. Build whisper.cpp
git clone https://github.com/ggerganov/whisper.cpp.git /opt/whisper.cpp
cd /opt/whisper.cpp && cmake -B build && cmake --build build --config Release -j$(nproc)
cp build/bin/whisper-cli /usr/local/bin/

# 3. Download model (small = 488 MB, multilingual, good speed/quality balance)
curl -L -o /usr/local/share/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

This is the same file the whatsapp skill's `setup.sh` downloads, so if you already
ran that, step 3 is done.

## Other Models

Sizes are the real `content-length` from huggingface.co, rounded to the nearest MB.

| Model | Size | Languages | Use when |
|-------|------|-----------|----------|
| ggml-tiny.bin | 78 MB | all | Speed matters more than accuracy |
| ggml-small.bin | 488 MB | all | Default, good balance |
| ggml-medium.bin | 1534 MB | all | Higher accuracy needed |
| ggml-large-v3-turbo.bin | 1625 MB | all | Best quality |

Each of these has an English-only `.en` twin (`ggml-small.en.bin` and so on) that is
slightly faster and marginally more accurate on English. The `.en` files are **not**
smaller: `ggml-small.en.bin` is 487,614,201 bytes against `ggml-small.bin`'s
487,601,967, so the multilingual model is the better default at no download cost.

An `.en` model cannot transcribe non-English audio. whisper.cpp rewrites `--language`
back to `en` and turns off `--translate` when the loaded model is English-only, so the
output is confident English nonsense rather than an error.

Download any model:
```bash
curl -L -o /usr/local/share/ggml-<model>.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-<model>.bin
```

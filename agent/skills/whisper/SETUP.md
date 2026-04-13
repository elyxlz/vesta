# Whisper Setup

```bash
# 1. Install build deps and ffmpeg
apt-get update && apt-get install -y build-essential cmake ffmpeg

# 2. Build whisper.cpp
git clone https://github.com/ggerganov/whisper.cpp.git /opt/whisper.cpp
cd /opt/whisper.cpp && cmake -B build && cmake --build build --config Release -j$(nproc)
cp build/bin/whisper-cli /usr/local/bin/

# 3. Download model (small.en = ~466MB, good speed/quality balance)
curl -L -o /usr/local/share/ggml-small.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin
```

## Other Models

| Model | Size | Use when |
|-------|------|----------|
| ggml-tiny.en.bin | 75 MB | Speed matters more than accuracy |
| ggml-small.en.bin | 466 MB | Default - good balance |
| ggml-medium.en.bin | 1.5 GB | Higher accuracy needed |
| ggml-large-v3-turbo.bin | 1.6 GB | Best quality, non-English support |

`.en` models are English-only but faster. For non-English audio, use a non-`.en` model with `--language`.

Download any model:
```bash
curl -L -o /usr/local/share/ggml-<model>.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-<model>.bin
```

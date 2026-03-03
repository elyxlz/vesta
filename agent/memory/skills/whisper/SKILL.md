---
name: whisper
description: Use for "transcribe", "transcription", "speech to text", "audio to text", "convert audio", or when the user wants text extracted from any audio or video file.
---

# Whisper — Local Audio Transcription

Transcribe audio/video files locally using whisper.cpp. No API calls, no data leaves the machine.

## Setup

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

### Other models

| Model | Size | Use when |
|-------|------|----------|
| ggml-tiny.en.bin | 75 MB | Speed matters more than accuracy |
| ggml-small.en.bin | 466 MB | Default — good balance |
| ggml-medium.en.bin | 1.5 GB | Higher accuracy needed |
| ggml-large-v3-turbo.bin | 1.6 GB | Best quality, non-English support |

`.en` models are English-only but faster. For non-English audio, use a non-`.en` model with `--language`.

Download any model:
```bash
curl -L -o /usr/local/share/ggml-<model>.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-<model>.bin
```

## Usage

```bash
# Basic transcription (any audio/video format — ffmpeg converts automatically)
~/memory/skills/whisper/scripts/whisper_transcribe.sh recording.mp3
~/memory/skills/whisper/scripts/whisper_transcribe.sh meeting.m4a
~/memory/skills/whisper/scripts/whisper_transcribe.sh video.mp4

# With options
~/memory/skills/whisper/scripts/whisper_transcribe.sh audio.wav --language es
~/memory/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --translate
~/memory/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --srt
~/memory/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --json
~/memory/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --model /usr/local/share/ggml-medium.en.bin
~/memory/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --threads 8
```

### Options

| Flag | Description |
|------|-------------|
| `--language <code>` | Language code (en, es, fr, de, etc.). Default: en |
| `--translate` | Translate non-English audio to English text |
| `--srt` | Output SRT subtitle format |
| `--json` | Output JSON with timestamps |
| `--model <path>` | Use a different model file |
| `--threads <n>` | CPU threads (default: 4) |

## Notes

- Accepts any format ffmpeg can read: mp3, m4a, wav, ogg, flac, mp4, webm, etc.
- Runs entirely local — no network, no API keys
- small.en processes ~15-30x faster than real-time on ARM64
- For long recordings (1h+), expect a few minutes of processing
- Output goes to stdout — pipe or redirect as needed

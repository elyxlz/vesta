---
name: whisper
description: Use for "transcribe", "transcription", "speech to text", "audio to text", "convert audio", or when the user wants text extracted from any audio or video file.
---

# Whisper - Local Audio Transcription

Transcribe audio/video files locally using whisper.cpp. No API calls, no data leaves the machine.

**Setup**: See [SETUP.md](SETUP.md)

## Usage

```bash
# Basic transcription (any audio/video format - ffmpeg converts automatically)
~/vesta/agent/skills/whisper/scripts/whisper_transcribe.sh recording.mp3
~/vesta/agent/skills/whisper/scripts/whisper_transcribe.sh meeting.m4a
~/vesta/agent/skills/whisper/scripts/whisper_transcribe.sh video.mp4

# With options
~/vesta/agent/skills/whisper/scripts/whisper_transcribe.sh audio.wav --language es
~/vesta/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --translate
~/vesta/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --srt
~/vesta/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --json
~/vesta/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --model /usr/local/share/ggml-medium.en.bin
~/vesta/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --threads 8
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
- Runs entirely local, no network, no API keys
- small.en processes ~15-30x faster than real-time on ARM64
- For long recordings (1h+), expect a few minutes of processing
- Output goes to stdout. Pipe or redirect as needed

---
name: whisper
description: Transcribe audio or video files to text (speech-to-text).
---

# Whisper - Local Audio Transcription

Transcribe audio/video files locally using whisper.cpp. No API calls, no data leaves the machine.

**Setup**: See [SETUP.md](SETUP.md)

## Usage

```bash
# Basic transcription (any audio/video format - ffmpeg converts automatically)
~/agent/skills/whisper/scripts/whisper_transcribe.sh recording.mp3
~/agent/skills/whisper/scripts/whisper_transcribe.sh meeting.m4a
~/agent/skills/whisper/scripts/whisper_transcribe.sh video.mp4

# With options
~/agent/skills/whisper/scripts/whisper_transcribe.sh audio.wav --language es
~/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --translate
~/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --srt
~/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --json
~/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --model /usr/local/share/ggml-medium.en.bin
~/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --threads 8
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

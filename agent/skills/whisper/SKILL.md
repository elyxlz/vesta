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
~/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --model /usr/local/share/ggml-medium.bin
~/agent/skills/whisper/scripts/whisper_transcribe.sh audio.mp3 --threads 8
```

### Options

| Flag | Description |
|------|-------------|
| `--language <code>` | Language code (en, es, fr, de, etc.). Default: `WHISPER_LANGUAGE`, or auto-detect when it is unset |
| `--translate` | Translate non-English audio to English text |
| `--srt` | Output SRT subtitle format |
| `--json` | Output JSON with timestamps |
| `--model <path>` | Use a different model file |
| `--threads <n>` | CPU threads (default: 4) |

## Notes

- Accepts any format ffmpeg can read: mp3, m4a, wav, ogg, flac, mp4, webm, etc.
- small processes ~15-30x faster than real-time on ARM64
- For long recordings (1h+), expect a few minutes of processing
- Output goes to stdout. Pipe or redirect as needed
- Default model is the multilingual `/usr/local/share/ggml-small.bin`, falling back to
  `ggml-small.en.bin`, `ggml-tiny.bin`, `ggml-tiny.en.bin` if that one is absent.
  Override with `WHISPER_MODEL` or `--model`. English-only `.en` models cannot
  transcribe other languages: whisper.cpp forces `--language en` and disables
  `--translate` on them
- Language is auto-detected per file. Set `WHISPER_LANGUAGE` to a whisper.cpp
  language code (`en`, `es`, `fr`, ...) to pin one for every run, the same
  variable the whatsapp CLI reads; `--language` overrides it for a single run
- For a user who speaks several languages, set `WHISPER_LANGUAGES` (comma list, primary
  first, e.g. `en,ar`): auto-detect still picks among them, but a clip detected as any
  other language is transcribed in the first listed one. `WHISPER_LANGUAGE` or
  `--language` still pin a single language
- `WHISPER_SECONDARY_MIN_P` (e.g. `0.85`, unset by default): with `WHISPER_LANGUAGES`, a listed
  language other than the first is used only when auto-detect reports at least this
  probability; below it the first listed language is used
- `WHISPER_PROMPT` (unset by default): a vocabulary hint passed as whisper's `--prompt` (trade
  terms, brand and place names). Applied only when decoding in `WHISPER_PROMPT_LANG` (default
  `en`), since a prompt in one language can pull other-language audio toward translation

`transcribe <file> [--language <code>]` turns an audio file into text: it asks the STT provider
configured in the voice skill first and falls back to the whisper skill's local whisper.cpp, and
the whatsapp daemon shells it for every incoming voice note. It is a console script of the voice
skill's CLI, so the installed tool needs one refresh for the command to exist on this box. Safe to
run more than once.

### 1. Refresh the voice CLI

```bash
uv tool install --editable ~/agent/skills/voice/cli
command -v transcribe
```

The install is transactional and a re-run over an existing install is a no-op. The last line must
print a path under `~/.local/bin`. If it fails, STOP, leave this migration unmarked, and report it
to the user.

### 2. Check that one transcription path works

Skip this step when the whatsapp skill is not active. Otherwise `transcribe` needs either an
enabled STT provider or the local whisper fallback:

```bash
voice-keys status
command -v whisper-cli || echo "no whisper-cli"
```

An enabled provider shows as `"stt": {..., "enabled": true}` in the first output. If there is none
and the second line prints `no whisper-cli`, incoming voice notes cannot be transcribed on this
box: follow `~/agent/skills/whisper/SETUP.md` to build `whisper-cli` (the `ggml-small.bin` model
is already present when the whatsapp skill's `setup.sh` ran), or offer the user Deepgram through
the voice skill.

### 3. Mark this migration applied

Call `mark_migration_applied` with `name="2026-09-voice-transcribe-command"`.

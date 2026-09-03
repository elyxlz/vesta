`transcribe <file> [--language <code>]` turns an audio file into text: it asks the STT provider
configured in the voice skill first and falls back to a local whisper.cpp build, and the whatsapp
daemon shells it for every incoming voice note. This box needs the console script on PATH and,
for the fallback, the `whisper-cli` binary and a model on disk. Every step checks before acting, so
this is safe to run more than once.

### 1. Refresh the voice CLI

```bash
uv tool install --editable ~/agent/skills/voice/cli
command -v transcribe
```

The install is transactional and a re-run over an existing install is a no-op. The last line must
print a path under `~/.local/bin`. If it fails, STOP, leave this migration unmarked, and report it
to the user.

### 2. Build the local whisper fallback if it is missing

The fallback needs `whisper-cli` and `/usr/local/share/ggml-small.bin`. Check both, and build only
what is absent (the compile takes a few minutes; the model is 488 MB):

```bash
command -v whisper-cli || {
  apt-get update && apt-get install -y build-essential cmake ffmpeg &&
  git clone https://github.com/ggerganov/whisper.cpp.git /opt/whisper.cpp 2>/dev/null;
  cd /opt/whisper.cpp && git pull --ff-only &&
  cmake -B build && cmake --build build --config Release -j"$(nproc)" &&
  cp build/bin/whisper-cli /usr/local/bin/
}
[ -f /usr/local/share/ggml-small.bin ] || curl -L -o /usr/local/share/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
command -v whisper-cli && [ -f /usr/local/share/ggml-small.bin ] && echo fallback-ready
```

If the last line prints `fallback-ready`, the local path works with no provider. If the build fails
(no disk, no network), the provider path still transcribes: tell the user the local fallback is not
built and point them at `~/agent/skills/voice/SETUP.md` section 4, then continue to step 3 anyway,
since a failed compile will not succeed on a later boot without their help.

### 3. Mark this migration applied

Call `mark_migration_applied` with `name="2026-09-voice-transcribe-command"`.

# Voice setup

## 1. Install the CLI

```bash
uv tool install --editable ~/agent/skills/voice/cli
```

Provides the `voice-server`, `voice-keys`, and `transcribe` commands. Re-run it whenever `[project.scripts]` in `cli/pyproject.toml` gains a command: an editable install picks up code changes on its own, but a new console script exists only after a reinstall.

## 2. Start the voice server

1. Start the daemon:
   ```bash
   voice-keys daemon start
   ```
   Idempotent (a running daemon is a no-op) and owns the register-service call (see [vestad](../vestad/SKILL.md)). Check with `voice-keys daemon status`, which reads the pid and port records at `~/agent/data/daemons/voice.pid` and `voice.port`; startup output lands in `~/agent/logs/voice.log`.
2. Read the `restart` skill and add this line to your restart daemons:
   ```
   voice-keys daemon start
   ```

## 3. API keys

Each user needs their own keys: one Deepgram key for STT (voice input), one ElevenLabs key for TTS (voice output). Keys stay on this container; they never transit vestad's config.

## Deepgram (STT, voice input)

**Dashboard:** https://console.deepgram.com

1. Sign in or create an account.
2. Go to **API Keys** in the left sidebar.
3. Click **Create a New API Key**.
4. Pick a role with at least these scopes:
   - `projects:read` (list project)
   - `usage:read` (monthly usage in Settings)
   - `billing:read` (remaining balance in Settings)
   - scopes for real-time transcription (the "Member" preset covers all of these)

   The **Admin** preset is easiest if you don't want to think about scopes.
5. Copy the generated key (a long hex string).
6. Paste it into chat for the agent to validate and save.

**Note:** new accounts get $200 free credit. The `flux-general-en` model is billed at roughly $0.0048/min of audio.

## ElevenLabs (TTS, voice output)

**Dashboard:** https://elevenlabs.io

1. Sign in or create an account.
2. Profile (top right) -> **My Account** -> **API Keys**.
3. Click **Create New Key**.
4. Give the key permission for:
   - **Text to Speech** (required for synthesis)
   - **Voices** (to list custom voices)
   - **User** (to read subscription/character count)
5. Copy the key (starts with `sk_`).
6. Paste it into chat for the agent to validate and save.

**Note:** free tier is 10k characters/month. Model `eleven_flash_v2_5`, output format `mp3_22050_32`.

## 4. Local transcription fallback (whisper.cpp)

`transcribe` asks the configured STT provider first (Deepgram above) and falls back to a local
whisper.cpp build when no provider is enabled or the provider call fails. The fallback needs the
`whisper-cli` binary and one model on disk. Build them once:

```bash
# Build deps and ffmpeg
apt-get update && apt-get install -y build-essential cmake ffmpeg

# whisper.cpp. Build from a dedicated source directory rather than /opt/whisper.cpp:
# some images already ship that path holding only prebuilt static libs and headers, with
# no .git and no CMakeLists.txt. Cloning into it is refused for being non-empty, and the
# cmake that follows then fails with a misleading "does not appear to contain
# CMakeLists.txt", so the cp never runs and the fallback is silently left unbuilt.
SRC=/opt/whisper.cpp-src
[ -d "$SRC/.git" ] || git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git "$SRC"
cmake -S "$SRC" -B "$SRC/build" && cmake --build "$SRC/build" --config Release -j"$(nproc)"
cp "$SRC/build/bin/whisper-cli" /usr/local/bin/

# Model: multilingual ggml-small (488 MB), the default the fallback looks for
curl -L -o /usr/local/share/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

The whatsapp skill's `setup.sh` downloads the same model, so if you already ran that only the
binary is missing. Other model sizes and the `WHISPER_MODEL` override live in the `whisper`
skill's SETUP.md.

## Adding a custom ElevenLabs voice

1. In the dashboard, open **Voices** -> **VoiceLab** or the Voice Library.
2. Create or clone a voice.
3. Copy the **Voice ID** (looks like `FGY2WhTYpPnrIDTdsKH5`).
4. Ask the agent in chat: "add this voice: <id> named <name>".

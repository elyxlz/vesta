# Voice setup

## 1. Install the CLI

```bash
uv tool install --editable ~/agent/skills/voice/cli
```

Provides the `voice` and `transcribe` commands. Re-run it whenever `cli/pyproject.toml` gains a command in `[project.scripts]` or a package in `dependencies`: an editable install picks up code changes on its own, but a new console script or package exists only after a reinstall.

## 2. Start the voice daemon

1. Start the daemon:
   ```bash
   voice daemon start
   ```
   Idempotent (a running daemon is a no-op) and owns the register-service call (see [vestad](../vestad/SKILL.md)). Check with `voice daemon status`, which reads the pid and port records at `~/agent/data/daemons/voice.pid` and `voice.port`; startup output lands in `~/agent/logs/voice.log`.
2. Read the `restart` skill and add this line to your restart daemons:
   ```
   voice daemon start
   ```

## 3. API keys

Each user needs their own keys. Deepgram and ElevenLabs can each do both jobs, STT (voice input) and TTS (voice output), so one key from either is enough for the whole flow, and a user can also mix them. The judge is optional and needs a TypeSafe key. Keys stay on this container; they never transit vestad's config. SKILL.md says how the providers differ.

## Deepgram (STT and TTS)

**Dashboard:** https://console.deepgram.com

1. Sign in or create an account.
2. Go to **API Keys** in the left sidebar.
3. Click **Create a New API Key**.
4. Pick a role with at least these scopes:
   - `projects:read` (list project)
   - `usage:read` (monthly usage in Settings)
   - `billing:read` (remaining balance in Settings)
   - scopes for real-time transcription, and for text to speech when Deepgram is the voice (the "Member" preset covers all of these)

   The **Admin** preset is easiest if you don't want to think about scopes.
5. Copy the generated key (a long hex string).
6. Paste it into chat for the agent to check and connect (`voice stt connect deepgram --key <key>`, and `voice tts connect deepgram --key <key>` for the voice).

**Note:** new accounts get $200 free credit. The `flux-general-en` model is billed at roughly $0.0048/min of audio, and Aura-2 speech at roughly $0.03 per 1000 characters.

## ElevenLabs (TTS and STT)

**Dashboard:** https://elevenlabs.io

1. Sign in or create an account.
2. Profile (top right) -> **My Account** -> **API Keys**.
3. Click **Create New Key**.
4. Give the key permission for:
   - **Text to Speech** (required for synthesis)
   - **Speech to Text** (when ElevenLabs is the mic)
   - **Voices** (to list custom voices)
   - **User** (to read subscription/character count)
5. Copy the key (starts with `sk_`).
6. Paste it into chat for the agent to check and connect (`voice tts connect elevenlabs --key <key>`, and `voice stt connect elevenlabs --key <key>` for the mic).

A key with fewer permissions still connects: each role checks only what it needs. Without **User**, the usage card in the app shows no number.

**Note:** free tier is 10k characters/month. Model `eleven_v4_turbo`.

## TypeSafe (the judge, optional)

TypeSafe makes Jev, the model that answers the judge's questions (its API is `api.typesafe.ai`).

1. The user creates an API key in their TypeSafe account.
2. They paste it into chat for the agent to check and connect (`voice judge connect typesafe --key <key>`), which turns the judge on.

With the judge on, the live transcript goes to TypeSafe. SKILL.md says what the judge does.

## 4. Local transcription fallback (whisper.cpp)

`transcribe` asks the configured STT provider first (Deepgram above) and falls back to a local
whisper.cpp build when no provider is enabled or the provider call fails. The fallback needs the
`whisper-cli` binary and one model on disk. Build them once:

```bash
# Build deps and ffmpeg
apt-get update && apt-get install -y build-essential cmake ffmpeg

# whisper.cpp
git clone https://github.com/ggerganov/whisper.cpp.git /opt/whisper.cpp
cd /opt/whisper.cpp && cmake -B build && cmake --build build --config Release -j"$(nproc)"
cp build/bin/whisper-cli /usr/local/bin/

# Model: multilingual ggml-small (488 MB), the default the fallback looks for
curl -L -o /usr/local/share/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

The whatsapp skill's `setup.sh` downloads the same model, so if you already ran that only the
binary is missing. Other model sizes and the `WHISPER_MODEL` override live in the `whisper`
skill's SETUP.md.

## 5. Wake word model (optional)

The wake word (SKILL.md) needs one ONNX classifier for its phrase, made with [livekit-wakeword](https://github.com/livekit/livekit-wakeword) (Apache-2.0). The detector runs on this box's CPU, one thread for each open session.

1. **Get the model file.** Training runs for hours on a machine with an NVIDIA GPU of 8 GB or more and more than 20 GB of free disk, so it is not a job for this box: ask the user for the file, or for a machine that can train it. On that machine:
   ```bash
   pip install "livekit-wakeword[train,eval,export]"
   git clone https://github.com/livekit/livekit-wakeword.git
   cp livekit-wakeword/configs/prod.yaml hey_aria.yaml
   ```
   In `hey_aria.yaml`, set `model_name: hey_aria` and `target_phrases: ["hey aria"]`, and replace `custom_negative_phrases` with phrases that sound like it and must not wake: `"aria"`, `"hey ari"`, `"area"`, `"hey area"`, `"hey siri"`, `"hey sarah"`, `"hey maria"`. Then:
   ```bash
   livekit-wakeword setup --config hey_aria.yaml
   livekit-wakeword run hey_aria.yaml
   ```
   `run` generates speech, trains, exports, and evaluates. The model is `output/hey_aria/hey_aria.onnx`, and the evaluation gives its false wakes per hour and its recall.
2. **Install it here**, at the path that `voice status` shows under `wake_word_model`:
   ```bash
   mkdir -p ~/.voice/wake_words && cp hey_aria.onnx ~/.voice/wake_words/hey_aria.onnx
   uv tool install --editable ~/agent/skills/voice/cli
   ```
   The second line installs the detector's packages when the voice CLI is older than them, and is a no-op when they are there.
3. **Turn it on**: `voice behavior set wake_word on`. `voice status` shows `"found": true` under `wake_word_model`.

A phrase other than `hey aria` needs its own model: train it with that phrase, name the file after its words (`hey_vesta.onnx` for `hey vesta`), and set `voice behavior set wake_word_phrase "hey vesta"`.

## Adding a custom ElevenLabs voice

1. In the dashboard, open **Voices** -> **VoiceLab** or the Voice Library.
2. Create or clone a voice.
3. Copy the **Voice ID** (looks like `FGY2WhTYpPnrIDTdsKH5`).
4. Ask the agent in chat: "add this voice: <id> named <name>".

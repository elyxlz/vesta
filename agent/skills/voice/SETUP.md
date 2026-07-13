# Voice setup

## 1. Install the CLI

```bash
uv tool install --editable ~/agent/skills/voice/cli
```

Provides the `voice-server` and `voice-keys` commands.

## 2. Start the voice server

1. Start the daemon:
   ```bash
   voice-keys daemon start
   ```
   Idempotent (a running daemon is a no-op) and owns the register-service call (see [vestad](../vestad/SKILL.md)), so there's nothing else to wire up. Check with `voice-keys daemon status`.
2. Add this startup command to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:
   ```
   voice-keys daemon start
   ```

## 3. API keys

Each user needs their own keys: one Deepgram key for STT (voice input), one ElevenLabs key for TTS (voice output). Keys stay on this container; they never transit vestad's configuration.

## Deepgram (STT, voice input)

**Dashboard:** https://console.deepgram.com

1. Sign in or create an account.
2. Go to **API Keys** in the left sidebar.
3. Click **Create a New API Key**.
4. Pick a role with at least these scopes:
   - `projects:read` (list project)
   - `usage:read` (monthly usage shown in Settings)
   - `billing:read` (remaining balance shown in Settings)
   - scopes for real-time transcription (the "Member" preset covers all of these)

   The **Admin** preset is easiest if you don't want to think about scopes.
5. Copy the generated key (a long hex string).
6. Paste it into chat for the agent to validate and save.

**Note:** new accounts get $200 free credit. The `flux-general-en` model is billed at roughly $0.0048/min of audio.

## ElevenLabs (TTS, voice output)

**Dashboard:** https://elevenlabs.io

1. Sign in or create an account.
2. Profile (top right) → **My Account** → **API Keys**.
3. Click **Create New Key**.
4. Give the key permission for:
   - **Text to Speech** (required for synthesis)
   - **Voices** (to list custom voices)
   - **User** (to read subscription/character count)
5. Copy the key (starts with `sk_`).
6. Paste it into chat for the agent to validate and save.

**Note:** free tier is 10k characters/month. Model `eleven_flash_v2_5`, output format `mp3_22050_32`.

## Adding a custom ElevenLabs voice

1. In the dashboard, open **Voices** → **VoiceLab** or the Voice Library.
2. Create or clone a voice.
3. Copy the **Voice ID** (looks like `FGY2WhTYpPnrIDTdsKH5`).
4. Ask the agent in chat: "add this voice: <id> named <name>".

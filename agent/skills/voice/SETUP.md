# Voice setup

## 1. Start the voice server

1. Register with vestad to get a port, then start the server in a background screen session:
   ```bash
   PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" \
     -H 'Content-Type: application/json' -d '{"name":"voice"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
   SKILL_PORT=$PORT PYTHONPATH=~/vesta/skills screen -dmS voice uv run python -m voice.server
   ```
2. Add to `~/vesta/prompts/restart.md`:
   ```
   PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"voice"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && SKILL_PORT=$PORT PYTHONPATH=~/vesta/skills screen -dmS voice uv run python -m voice.server
   ```

## 2. API keys

Each user needs their own API keys — one Deepgram key for STT (voice input) and one ElevenLabs key for TTS (voice output). Keys stay on this container; they never transit vestad's configuration.

## Deepgram (STT — voice input)

**Dashboard:** https://console.deepgram.com

**Steps:**
1. Sign in or create an account.
2. Go to **API Keys** in the left sidebar.
3. Click **Create a New API Key**.
4. Pick a role with at least these scopes:
   - `projects:read` — list project
   - `usage:read` — fetch the monthly usage shown in Settings
   - `billing:read` — fetch the remaining balance shown in Settings
   - scopes for real-time transcription (the "Member" preset covers all of these)
   
   The **Admin** preset is the easiest choice if you don't want to think about scopes.
5. Copy the generated key (starts with a long hex string).
6. Paste it into chat for the agent to validate and save.

**Note:** Deepgram gives new accounts $200 of free credit. The `flux-general-en` model used here is billed at roughly $0.0048/min of audio.

## ElevenLabs (TTS — voice output)

**Dashboard:** https://elevenlabs.io

**Steps:**
1. Sign in or create an account.
2. Click your profile (top right) → **My Account** → **API Keys**.
3. Click **Create New Key**.
4. Give the key permission for:
   - **Text to Speech** (required for speech synthesis)
   - **Voices** (needed to list custom voices)
   - **User** (needed to read subscription/character count)
5. Copy the key (starts with `sk_`).
6. Paste it into chat for the agent to validate and save.

**Note:** ElevenLabs free tier is 10k characters/month. The model used here is `eleven_flash_v2_5` with `mp3_22050_32` output format.

## Adding a custom ElevenLabs voice

1. In the ElevenLabs dashboard, open **Voices** → **VoiceLab** or the Voice Library.
2. Create or clone a voice.
3. Copy the **Voice ID** (looks like `FGY2WhTYpPnrIDTdsKH5`).
4. Ask the agent in chat: "add this voice: <id> named <name>".

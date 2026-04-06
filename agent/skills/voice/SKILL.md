---
name: voice
description: Use when the user asks to enable voice input/output, set up transcription or text-to-speech, rotate API keys, add custom voices, adjust the transcription sensitivity, or talks about the microphone/speaker in the Vesta app. This skill manages ~/.voice/voice_config.json — the single source of truth for STT/TTS keys, voice selection, keyterms, and thresholds.
serve: PYTHONPATH=~/vesta/skills SKILL_PORT=7965 uv run python -m voice.server
---

# Voice setup (STT/TTS)

This skill turns on the microphone button and "read responses aloud" toggle in the Vesta app. It owns `~/.voice/voice_config.json` and exposes the HTTP/WS endpoints the frontend calls for streaming transcription and speech synthesis.

## When to offer setup

- User mentions voice, microphone, speaking aloud, hearing you, TTS, STT, transcription
- User complains the mic button is disabled or they can't hear you
- New container, user hasn't set up voice yet — offer once early, then drop it (track in memory so you don't nag)

## The setup flow

0. **Start the voice server** — follow [SETUP.md](SETUP.md) section 1. The `restart.md` entries relaunch the screen session and re-register the service on boot.
1. **Ask which provider(s) they want** — Deepgram for input (STT), ElevenLabs for output (TTS). Both are independent; the user may configure only one.
2. **Walk them through signup** — see [SETUP.md](SETUP.md) section 2 for the per-provider link, required scopes, and where to find the key.
3. **Validate the key** before saving:
   ```bash
   uv run ~/vesta/skills/voice/scripts/voice_keys.py validate --provider deepgram --key <key>
   ```
4. **Save the key** with `set-key`:
   ```bash
   uv run ~/vesta/skills/voice/scripts/voice_keys.py set-key --domain stt --provider deepgram --key <key>
   ```
5. **Confirm to the user** — e.g. "STT set up with Deepgram. Mic button should work now." The UI picks up changes on its next fetch.

## Commands

```bash
# See current state
uv run ~/vesta/skills/voice/scripts/voice_keys.py status

# Keys
uv run ~/vesta/skills/voice/scripts/voice_keys.py validate --provider {deepgram|elevenlabs} --key <k>
uv run ~/vesta/skills/voice/scripts/voice_keys.py set-key --domain {stt|tts} --provider {deepgram|elevenlabs} --key <k>
uv run ~/vesta/skills/voice/scripts/voice_keys.py clear --domain {stt|tts}

# TTS voice selection
uv run ~/vesta/skills/voice/scripts/voice_keys.py set-voice --id <voice_id>
uv run ~/vesta/skills/voice/scripts/voice_keys.py add-voice --id <voice_id> --name <name>
uv run ~/vesta/skills/voice/scripts/voice_keys.py remove-voice --id <voice_id>

# STT keyterms (words the transcription should bias toward)
uv run ~/vesta/skills/voice/scripts/voice_keys.py add-keyterm <term>
uv run ~/vesta/skills/voice/scripts/voice_keys.py remove-keyterm <term>

# STT end-of-turn tuning
uv run ~/vesta/skills/voice/scripts/voice_keys.py set-eot --threshold 0.8
uv run ~/vesta/skills/voice/scripts/voice_keys.py set-eot --timeout-ms 10000
```

## Common asks

- **"Add the voice with id X named Y"** → `add-voice --id X --name Y`
- **"I want you to sound like <name>"** → `set-voice --id <matching voice_id from status>`
- **"Make sure you recognize '{AGENT_NAME}'"** → `add-keyterm {AGENT_NAME}`
- **"Finalize my turns faster"** → lower `--threshold` (e.g. 0.6)
- **"Stop cutting me off"** → raise `--threshold` (e.g. 0.9) or raise `--timeout-ms`

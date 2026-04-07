---
name: voice
description: Use when the user asks to enable/disable voice input/output, set up transcription or text-to-speech, rotate API keys, add custom voices, adjust the transcription sensitivity, or talks about the microphone/speaker in the Vesta app. This skill manages ~/.voice/voice_config.json — the single source of truth for STT/TTS keys, voice selection, keyterms, and thresholds. Use enable/disable to toggle without removing configuration; use clear only to wipe keys entirely.
serve: see SETUP.md — requires a port from vestad
---

# Voice setup (STT/TTS)

Voice lets the user talk to you through the mic and hear your responses spoken aloud in the Vesta app.

Once configured, the user can manage voice settings directly from the **agent settings page** in the app — including changing voices, listening to voice previews, toggling STT/TTS on or off, and adjusting sensitivity. Let them know this after setup.

## When to offer setup

- User mentions voice, microphone, speaking aloud, hearing you, TTS, STT, transcription
- User complains the mic button is disabled or they can't hear you
- New container, user hasn't set up voice yet — offer once early, then drop it (track in memory so you don't nag)

## The setup flow

1. **Ask which they want** — Deepgram for input (speech-to-text), ElevenLabs for output (text-to-speech). Both are independent; the user may configure only one.
2. **Walk them through getting a key** — see [SETUP.md](SETUP.md) for the per-provider link and where to find the key.
3. **Validate the key** before saving:
   ```bash
   uv run ~/vesta/skills/voice/scripts/voice_keys.py validate --provider deepgram --key <key>
   ```
4. **Save the key**:
   ```bash
   uv run ~/vesta/skills/voice/scripts/voice_keys.py set-key --domain stt --provider deepgram --key <key>
   ```
5. **Confirm** — e.g. "Voice is ready! You can use the mic button now. You can also change voices, listen to previews, and tweak settings from the settings page in the app."

## Commands

```bash
# See current state
uv run ~/vesta/skills/voice/scripts/voice_keys.py status

# Keys
uv run ~/vesta/skills/voice/scripts/voice_keys.py validate --provider {deepgram|elevenlabs} --key <k>
uv run ~/vesta/skills/voice/scripts/voice_keys.py set-key --domain {stt|tts} --provider {deepgram|elevenlabs} --key <k>
uv run ~/vesta/skills/voice/scripts/voice_keys.py clear --domain {stt|tts}   # removes provider + keys entirely

# Enable/disable (keeps configuration intact, just toggles on/off)
uv run ~/vesta/skills/voice/scripts/voice_keys.py enable --domain {stt|tts}
uv run ~/vesta/skills/voice/scripts/voice_keys.py disable --domain {stt|tts}

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

- **"Disable TTS / stop speaking"** → `disable --domain tts` (keeps keys, just turns it off)
- **"Enable TTS / start speaking again"** → `enable --domain tts`
- **"Disable STT / turn off the mic"** → `disable --domain stt`
- **"Remove voice completely"** → `clear --domain tts` (wipes provider + keys)
- **"Add the voice with id X named Y"** → `add-voice --id X --name Y` (description auto-fetched from ElevenLabs)
- **"I want you to sound like <name>"** → `set-voice --id <matching voice_id from status>` (or tell them they can browse and preview voices in the app settings)
- **"Make sure you recognize '{AGENT_NAME}'"** → `add-keyterm {AGENT_NAME}`
- **"Finalize my turns faster"** → lower `--threshold` (e.g. 0.6)
- **"Stop cutting me off"** → raise `--threshold` (e.g. 0.9) or raise `--timeout-ms`

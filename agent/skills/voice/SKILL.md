---
name: voice
description: Use when the user asks to enable/disable voice input/output, set up transcription or text-to-speech, rotate API keys, add custom voices, adjust the transcription sensitivity, or talks about the microphone/speaker in the Vesta app. This skill manages ~/.voice/voice_config.json - the single source of truth for STT/TTS keys, voice selection, keyterms, and thresholds. Use enable/disable to toggle without removing configuration; use clear only to wipe keys entirely.
serve: PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"voice"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && SKILL_PORT=$PORT PYTHONPATH=~/vesta/skills screen -dmS voice uv run python -m voice.server
---

# Voice setup (STT/TTS)

Voice lets the user talk to you through the mic and hear your responses spoken aloud in the Vesta app.

Once configured, the user can manage voice settings directly from the **agent settings page** in the app - including changing voices, listening to voice previews, toggling STT/TTS on or off, and adjusting sensitivity. Let them know this after setup.

## When to offer setup

- User mentions voice, microphone, speaking aloud, hearing you, TTS, STT, transcription
- User complains the mic button is disabled or they can't hear you
- New container, user hasn't set up voice yet - offer once early, then drop it (track in memory so you don't nag)

## The setup flow

1. **Ask which they want** - Deepgram for input (speech-to-text), ElevenLabs for output (text-to-speech). Both are independent; the user may configure only one.
2. **Walk them through getting a key** - see [SETUP.md](SETUP.md) for the per-provider link and where to find the key.
3. **Validate the key** before saving:
   ```bash
   uv run ~/vesta/skills/voice/scripts/voice_keys.py validate --provider deepgram --key <key>
   ```
4. **Save the key**:
   ```bash
   uv run ~/vesta/skills/voice/scripts/voice_keys.py set-key --domain stt --provider deepgram --key <key>
   ```
5. **Pick a voice** (TTS only) - Ask the user if they'd prefer a male or female voice, then set an appropriate default:
   - Male voices: Roger (laid-back), Charlie (deep, Australian), George (warm, British), Liam (energetic), Chris (charming), Brian (deep, resonant), Daniel (steady, British)
   - Female voices: Sarah (mature), Laura (enthusiastic), Alice (clear, British), Matilda (professional), Jessica (playful), Lily (velvety, British)
   ```bash
   uv run ~/vesta/skills/voice/scripts/voice_keys.py set-voice --id <voice_id>
   ```
   Let them know they can browse all voices and listen to previews in the app settings later.
6. **Ensure the voice server is running** - the app fetches config from it. Check with `screen -ls | grep voice`. If it's not running, start it:
   ```bash
   PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"voice"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
   SKILL_PORT=$PORT PYTHONPATH=~/vesta/skills screen -dmS voice uv run python -m voice.server
   ```
7. **Confirm** - e.g. "Voice is ready! You can use the mic button now. You can also change voices, listen to previews, and tweak settings from the settings page in the app."

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
uv run ~/vesta/skills/voice/scripts/voice_keys.py add-voice --id <voice_id> --name <name> --description "..."
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
- **"I want you to sound like <name>"** → `set-voice --id <matching voice_id from status>` (or tell them they can browse and preview voices in the app settings)
- **"Make sure you recognize '{AGENT_NAME}'"** → `add-keyterm {AGENT_NAME}`
- **"Finalize my turns faster"** → lower `--threshold` (e.g. 0.6)
- **"Stop cutting me off"** → raise `--threshold` (e.g. 0.9) or raise `--timeout-ms`

## Providers

### Deepgram (STT, voice input)

- Domain: `stt`, provider name: `deepgram`
- Model: `flux-general-en` (~$0.0048/min)
- New accounts get $200 free credit
- Keyterms bias the transcription toward specific words (e.g. the agent's name)
- End-of-turn detection is tuned via `--threshold` (confidence, 0-1) and `--timeout-ms` (silence timeout)

### ElevenLabs (TTS, voice output)

- Domain: `tts`, provider name: `elevenlabs`
- Model: `eleven_flash_v2_5`, output format: `mp3_22050_32`
- Free tier: 10k characters/month
- Ships with premade voices; users can also add custom/cloned voices from their ElevenLabs account
- **Adding a voice**: when the user provides an ElevenLabs voice ID without a name or description, fetch them from the API before calling `add-voice`:
  ```bash
  curl -s https://api.elevenlabs.io/v1/voices/<id> | python3 -c "
  import sys,json; v=json.load(sys.stdin); l=v.get('labels',{})
  print(v.get('name',''))
  print(', '.join(p for p in [l.get('description',''),l.get('accent',''),l.get('gender','')] if p))"
  ```
  Use the first line as `--name` and the second as `--description`. If the fetch fails, ask the user.

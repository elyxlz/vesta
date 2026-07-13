---
name: voice
description: Voice input/output, transcription, TTS, API keys; manages ~/.voice/voice_config.json.
serve: voice-keys daemon start
---

# Voice setup (STT/TTS)

Lets the user talk to you via mic and hear responses in the Vesta app. The one voice backend: owns STT/TTS providers, keys, and chosen voice, so anything that speaks or listens uses the same config.

Once configured, the user manages voice settings from the **agent settings page**: change voices, hear previews, toggle STT/TTS, adjust sensitivity. Tell them this after setup.

## When to offer setup

- User mentions voice, mic, speaking aloud, hearing you, TTS, STT, transcription
- User says the mic button is disabled or they can't hear you
- New container, voice not set up. Offer once early, then drop it (track in memory)

## The setup flow

1. **Ask which they want**: Deepgram for input (STT), ElevenLabs for output (TTS). Independent; may configure only one.
2. **Walk them through getting a key**: see [SETUP.md](SETUP.md) for the per-provider link and where to find the key.
3. **Validate before saving**:
   ```bash
   voice-keys validate --provider deepgram --key <key>
   ```
4. **Save the key**:
   ```bash
   voice-keys set-key --domain stt --provider deepgram --key <key>
   ```
5. **Pick a voice** (TTS only). Ask male or female, then set a default:
   - Male: Roger (laid-back), Charlie (deep, Australian), George (warm, British), Liam (energetic), Chris (charming), Brian (deep, resonant), Daniel (steady, British)
   - Female: Sarah (mature), Laura (enthusiastic), Alice (clear, British), Matilda (professional), Jessica (playful), Lily (velvety, British)
   ```bash
   voice-keys set-voice --id <voice_id>
   ```
   They can browse all voices and hear previews in app settings later.
6. **Ensure the voice server is running** (the app fetches config from it):
   ```bash
   voice-keys daemon start
   ```
   Idempotent and the only command needed. Check with `voice-keys daemon status`.
7. **Confirm**, e.g. "Voice is ready! Use the mic button now. Change voices, hear previews, and tweak settings from the app settings page."

## Commands

**Daemon**: `voice-keys daemon start|stop|restart|status`. Start is idempotent (never stacks a duplicate) and owns the register-service call; status reports the port plus each domain's provider and enabled state. Manage the daemon only through these commands, never raw `screen`.

```bash
# See current state
voice-keys status

# Keys
voice-keys validate --provider {deepgram|elevenlabs} --key <k>
voice-keys set-key --domain {stt|tts} --provider {deepgram|elevenlabs} --key <k>
voice-keys clear --domain {stt|tts}   # removes provider + keys entirely

# Enable/disable (keeps config, just toggles on/off)
voice-keys enable --domain {stt|tts}
voice-keys disable --domain {stt|tts}

# TTS voice selection
voice-keys set-voice --id <voice_id>
voice-keys add-voice --id <voice_id> --name <name> --description "..."
voice-keys remove-voice --id <voice_id>

# STT keyterms (words transcription should bias toward)
voice-keys add-keyterm <term>
voice-keys remove-keyterm <term>

# STT end-of-turn tuning
voice-keys set-eot --threshold 0.8
voice-keys set-eot --timeout-ms 10000
```

## Common asks

- **"Disable TTS / stop speaking"** -> `disable --domain tts` (keeps keys)
- **"Enable TTS / start speaking again"** -> `enable --domain tts`
- **"Disable STT / turn off the mic"** -> `disable --domain stt`
- **"Remove voice completely"** -> `clear --domain tts` (wipes provider + keys)
- **"I want you to sound like <name>"** -> `set-voice --id <matching voice_id from status>` (or point them to app settings)
- **"Make sure you recognize '{AGENT_NAME}'"** -> `add-keyterm {AGENT_NAME}`
- **"Finalize my turns faster"** -> lower `--threshold` (e.g. 0.6)
- **"Stop cutting me off"** -> raise `--threshold` (e.g. 0.9) or raise `--timeout-ms`

## Providers

### Deepgram (STT, voice input)

- Domain: `stt`, provider name: `deepgram`
- Model: `flux-general-en` (~$0.0048/min)
- New accounts get $200 free credit
- Keyterms bias transcription toward specific words (e.g. the agent's name)
- End-of-turn detection tuned via `--threshold` (confidence, 0-1) and `--timeout-ms` (silence timeout)

### ElevenLabs (TTS, voice output)

- Domain: `tts`, provider name: `elevenlabs`
- Model: `eleven_flash_v2_5`, output format: `mp3_22050_32`
- Free tier: 10k characters/month
- Ships with premade voices; users can add custom/cloned voices from their ElevenLabs account
- **Adding a voice**: when the user gives an ElevenLabs voice ID without a name/description, fetch them from the API before `add-voice`:
  ```bash
  curl -s https://api.elevenlabs.io/v1/voices/<id> | python3 -c "
  import sys,json; v=json.load(sys.stdin); l=v.get('labels',{})
  print(v.get('name',''))
  print(', '.join(p for p in [l.get('description',''),l.get('accent',''),l.get('gender','')] if p))"
  ```
  Use line 1 as `--name`, line 2 as `--description`. If the fetch fails, ask the user.

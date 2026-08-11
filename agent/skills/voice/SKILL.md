---
name: voice
description: Voice input/output, transcription, TTS, API keys; manages ~/.voice/voice_config.json.
---

# Voice setup (STT/TTS)

Voice lets the user talk to you through the mic and hear your responses spoken aloud in the Vesta app.

This skill is also your one voice backend: it owns the STT/TTS providers, keys, and chosen voice, so anything that speaks or listens on your behalf uses the same voice; setting it up here is what turns them on.

## When to offer setup

- User mentions voice, microphone, speaking aloud, hearing you, TTS, STT, transcription
- User complains the mic button is disabled or they can't hear you
- New container, user hasn't set up voice yet. Offer once early, then drop it (track in memory so you don't nag)

## The setup flow

1. **Ask which they want**: Deepgram for input (speech-to-text), ElevenLabs for output (text-to-speech). Both are independent; the user may configure only one.
2. **Walk them through getting a key**: see [SETUP.md](SETUP.md) for the per-provider link and where to find the key.
3. **Validate the key** before saving:
   ```bash
   voice-keys validate --provider deepgram --key <key>
   ```
4. **Save the key**:
   ```bash
   voice-keys set-key --domain stt --provider deepgram --key <key>
   ```
5. **Pick a voice** (TTS only). Ask the user if they'd prefer a male or female voice, then set an appropriate default:
   - Male voices: Roger (laid-back), Charlie (deep, Australian), George (warm, British), Liam (energetic), Chris (charming), Brian (deep, resonant), Daniel (steady, British)
   - Female voices: Sarah (mature), Laura (enthusiastic), Alice (clear, British), Matilda (professional), Jessica (playful), Lily (velvety, British)
   ```bash
   voice-keys set-voice --id <voice_id>
   ```
6. **Ensure the voice server is running.** The app fetches config from it.
   ```bash
   voice-keys daemon start
   ```
   Check with `voice-keys daemon status`.
7. **Confirm**, e.g. "Voice is ready! You can use the mic button now. You can also change voices, listen to previews, and tweak settings from the settings page in the app."

## Commands

**Daemon**: `voice-keys daemon start|stop|restart|status`. Start is idempotent (never stacks a duplicate) and owns the register-service call; stop is the deliberate shutdown, so it does not fire the `daemon_died` notification every other exit fires; status reports whether the server is up and on which port. Provider and enabled state come from `voice-keys status`. Manage the daemon only through these commands, never by launching `voice-server` yourself.

```bash
# See current state
voice-keys status

# Keys
voice-keys validate --provider {deepgram|elevenlabs} --key <k>
voice-keys set-key --domain {stt|tts} --provider {deepgram|elevenlabs} --key <k>
voice-keys clear --domain {stt|tts}   # removes provider + keys entirely

# Enable/disable (keeps configuration intact, just toggles on/off)
voice-keys enable --domain {stt|tts}
voice-keys disable --domain {stt|tts}

# TTS voice selection
voice-keys set-voice --id <voice_id>
voice-keys add-voice --id <voice_id> --name <name> --description "..."
voice-keys remove-voice --id <voice_id>

# STT keyterms (words the transcription should bias toward)
voice-keys add-keyterm <term>
voice-keys remove-keyterm <term>

# STT end-of-turn tuning
voice-keys set-eot --threshold 0.8
voice-keys set-eot --timeout-ms 10000
```

## Common asks

- **"Disable TTS / stop speaking"** → `disable --domain tts` (keeps keys, just turns it off)
- **"Enable TTS / start speaking again"** → `enable --domain tts`
- **"Disable STT / turn off the mic"** → `disable --domain stt`
- **"Remove voice completely"** → `clear --domain tts` (wipes provider + keys)
- **"I want you to sound like <name>"** → `set-voice --id <matching voice_id from status>`
- **"Make sure you recognize '{AGENT_NAME}'"** → `add-keyterm {AGENT_NAME}`
- **"Finalize my turns faster"** → lower `--threshold` (e.g. 0.6)
- **"Stop cutting me off"** → raise `--threshold` (e.g. 0.9) or raise `--timeout-ms`

## Manual re-transcription (when auto-STT is wrong/incomplete)

When the live whisper transcription comes back wrong-language, junk (`[Musica]`, `[BLANK_AUDIO]`), or **cuts off mid-thought** (incomplete), re-transcribe the source audio directly via Deepgram before acting on it. Never act on a transcription you suspect is truncated.

**Step 1: get the audio.** For a WhatsApp voice note, download it by message ID (correct flags below; the message ID comes from the inbound notification):
```bash
whatsapp download-media -message-id <MSG_ID> -to '<chat_jid>' -download-path /tmp/vn.ogg
```

**Step 2: POST to Deepgram Nova-3.** The Deepgram key is **nested**, not top-level: it lives at `voice_config.json` → `stt` → `credentials` → `deepgram` → `api_key`. (Hunting this cost 2 calls on 10/08; the shallow path 401s, `['api_key']` is the fix.) Force `language=it`:
```bash
/usr/bin/python3 - <<'PY'
import json,urllib.request
key=json.load(open('/root/.voice/voice_config.json'))['stt']['credentials']['deepgram']['api_key']
req=urllib.request.Request(
    "https://api.deepgram.com/v1/listen?model=nova-3&language=it&smart_format=true",
    data=open('/tmp/vn.ogg','rb').read(),
    headers={"Authorization":f"Token {key}","Content-Type":"audio/ogg"})
print(json.loads(urllib.request.urlopen(req,timeout=30).read())['results']['channels'][0]['alternatives'][0]['transcript'])
PY
```
Clean up `/tmp/vn.ogg` after. User preference still holds: voice is input only, confirm receipt, don't send the transcription back unless asked.

## Providers

### Deepgram (STT, voice input)

- Domain: `stt`, provider name: `deepgram`
- Model: `flux-general-en` (~$0.0048/min)
- New accounts get $200 free credit
- Keyterms bias the transcription toward specific words (e.g. the agent's name)

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

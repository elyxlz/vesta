---
name: voice
description: Voice input/output, transcription, TTS, speech providers and their API keys, local speech models, a voice client of your own; manages ~/.voice/voice_config.json.
---

# Voice (CLI: voice)

Voice lets the user talk to you through the mic and hear your responses spoken aloud in the Vesta app.

This skill is also your one voice backend: it owns the speech providers, their keys, and the chosen voice, so anything that speaks or listens on your behalf uses the same voice; setting it up here is what turns them on.

## When to offer setup

- User mentions voice, microphone, speaking aloud, hearing you, TTS, STT, transcription
- User complains the mic button is disabled or they can't hear you
- New container, user hasn't set up voice yet. Offer once early, then drop it (track in memory so you don't nag)

## Roles and providers

A **role** is one job a provider does. A provider is **connected** to a role once the role holds its key, one connected provider is **selected**, and a role is **on** or **off**.

| Role | Job | Providers |
| --- | --- | --- |
| `stt` | speech to text (the mic) | `deepgram` (Flux), `elevenlabs` (Scribe) |
| `tts` | text to speech (your voice) | `elevenlabs` (`eleven_v4_turbo`), `deepgram` (Aura-2) |
| `judge` | decides who the user's words are for while you speak | `typesafe` (Jev) |

`stt` and `tts` are independent: the user may set up only one. One ElevenLabs key works for both roles and so does one Deepgram key, and each role stores its own copy, so connect the key to each role you want.

## The setup flow

1. **Ask which they want**, and which provider. With no preference: Deepgram for `stt` and ElevenLabs for `tts`. A user with one key connects that provider to both roles.
2. **Walk them through getting a key**: see [SETUP.md](SETUP.md) for the per-provider link and where to find the key.
3. **Connect the provider.** `connect` tests the key for that role, stores it, selects the provider, and turns the role on:
   ```bash
   voice stt connect deepgram --key <key>
   voice tts connect elevenlabs --key <key>
   ```
   `voice <role> check <provider> --key <key>` runs the same test and stores nothing.
4. **Ensure the voice daemon is running.** The app fetches config from it.
   ```bash
   voice daemon start
   ```
   Check with `voice daemon status`.
5. **Pick a voice** (TTS only). Ask the user if they'd prefer a male or female voice, then set one:
   ```bash
   voice tts voice <voice_id>
   ```
   - ElevenLabs male voices: Roger (laid-back), Charlie (deep, Australian), George (warm, British), Liam (energetic), Chris (charming), Brian (deep, resonant), Daniel (steady, British)
   - ElevenLabs female voices: Sarah (mature), Laura (enthusiastic), Alice (clear, British), Matilda (professional), Jessica (playful), Lily (velvety, British)
   - Deepgram: a voice speaks one language, so pick one in the user's language. Its ID is `aura-2-<voice>-<language>`: `aura-2-thalia-en`, `aura-2-apollo-en`, `aura-2-melia-it`, `aura-2-elio-it`.

   The voice IDs, every other voice, and each one's description are the options of the voice setting:
   ```bash
   curl -s "http://localhost:$(voice daemon status | python3 -c 'import sys,json; print(json.load(sys.stdin)["port"])')/tts/status"
   ```
6. **Confirm**, e.g. "Voice is ready! You can use the mic button now. You can also change voices, listen to previews, and tweak settings from the settings page in the app."

## Which provider

Tell the user the difference when they ask which one to pick.

**Speech to text.** Flux predicts the end of a turn from the words. Scribe (`scribe_v3_live`) predicts it too and falls back to the silence setting, which stays its upper bound.

| | `deepgram` (Flux) | `elevenlabs` (Scribe) |
| --- | --- | --- |
| A complete sentence ends the turn after | 0.3 s to 0.8 s | the silence setting plus about 0.3 s (about 1.1 s at the default) |
| A sentence that stops in the middle | waits about 3 s for the rest | ends like any other |
| A pause inside a turn | one turn | two turns, when the pause is longer than the silence setting |
| Live text | word by word | in blocks, about each second |
| Languages | English, or many with `voice stt set multi_language on` | more than 90, detected |
| Tuning | `eot_threshold`, `eot_timeout_ms` | `vad_silence_threshold_secs` (0.5 to 3.0) |

**Text to speech.**

| | `elevenlabs` | `deepgram` (Aura-2) |
| --- | --- | --- |
| Language | one voice speaks many languages | each voice speaks one: English, Spanish, German, French, Dutch, Italian, or Japanese |
| Voices | 19, plus voice IDs from the user's ElevenLabs account | 90 |
| Text in square brackets | an instruction, not speech (see below) | plain text |

**The judge** turns on when its key is connected. With it on, your live transcript and the line you are saying go to TypeSafe on every word the user says, so say that before you connect it. What it buys: a short "stop" cuts you off at once, an "mhm" does not, and words meant for someone else in the room stay out of the conversation. With it off, a user who talks over you for a second takes the floor, and a shorter sound lets you continue.

```bash
voice judge connect typesafe --key <key>
voice judge off   # to stop sending text to TypeSafe and keep the key
```

Once the judge is connected, the user can also turn it on and off in the voice settings of the app, where its card says what it sends to its provider.

## Text you speak

With ElevenLabs selected, text in square brackets is an instruction to the voice and is not read aloud: `[laughs]`, `[whispering]`, `[sighs]`. Use it only when you mean it, and never put text you want heard in square brackets. With Deepgram selected, write no such tags: they are plain text there.

You do not need to check which provider is selected before each reply. While `tts` is on, the `reply_hint` of each app message whose reply the app reads aloud carries the rule of the selected provider. A hint with no such rule means that the reply is not read aloud, or that the voice says each character.

## Commands

Every command prints one line of JSON on stdout. A command that fails prints `{"error": ...}` on stderr and exits non-zero. `<role>` is `stt`, `tts`, or `judge`.

```bash
# Every role (its providers, the connected ones, the selected one, on or off, its settings) and every behavior
voice status

# Providers
voice <role> check <provider> [--key <k>]     # test a provider for a role; stores nothing
voice <role> connect <provider> [--key <k>]   # test it, store it, select it
voice <role> use <provider>                   # switch to a connected provider; needs no key
voice <role> disconnect <provider>            # remove its key; the next connected provider takes over
voice <role> on
voice <role> off                              # keeps the keys

# Settings of the selected provider, and behaviors
voice <role> set <key> <value>                # voice stt set eot_threshold 0.7
voice behavior set <key> <value>              # voice behavior set barge_in off

# TTS voice
voice tts voice <voice_id>
voice tts voices add <voice_id> --name <name> [--description "..."]
voice tts voices remove <voice_id>

# STT key terms (words the transcription should bias toward)
voice stt keyterms add <term>
voice stt keyterms remove <term>

# One audio or video file to text (provider first, local whisper fallback)
transcribe ~/note.ogg
transcribe ~/meeting.mp4 --language it
```

`--key` is necessary for a provider that needs a key and refused for one that needs none. A setting belongs to one provider and each provider keeps its own, so `voice <role> use` loses nothing: switch back and the voice, the tuning, and the key are as they were.

**Behaviors** change how every session acts, whichever provider is selected. `barge_in` (on by default) lets the user stop a spoken reply by talking over it. With it off, a reply plays to its end or until the user stops it on the device. It applies to a conversation. In dictation the user talks to the message box, so their voice never stops a reply.

**Transcribe a file**: `transcribe <file> [--language <code>]` prints the transcript of any audio or video file on stdout and nothing else. It sends the file to the selected STT provider (language detected unless `--language` pins one such as `it`) and, when STT is unset, off, or the provider fails, runs the whisper skill's local whisper.cpp instead; it prints `{"error": ...}` on stderr and exits non-zero only when both fail. Every skill that needs speech as text calls this one command (the whatsapp daemon runs it on each incoming voice note), so a transcription problem anywhere is fixed here: check `voice status`, then the whisper skill's setup.

**Daemon**: `voice daemon start|stop|restart|status`. Start is idempotent (never stacks a duplicate) and owns the register-service call; stop is the deliberate shutdown, so it does not fire the `daemon_died` notification every other exit fires; status reports whether the service is up and on which port. A session reads its providers and settings when it opens, so a change applies to the next session with no restart. Manage the daemon only through these commands, never by running `voice serve` yourself.

## Common asks

- **"Disable TTS / stop speaking"** → `voice tts off` (keeps keys, just turns it off)
- **"Enable TTS / start speaking again"** → `voice tts on`
- **"Disable STT / turn off the mic"** → `voice stt off`
- **"Remove voice completely"** → `voice tts disconnect <provider>` for each connected provider
- **"I want you to sound like <name>"** → `voice tts voice <matching voice_id>`
- **"Make sure you recognize '{AGENT_NAME}'"** → `voice stt keyterms add {AGENT_NAME}`
- **"Finalize my turns faster"** → Flux: `voice stt set eot_threshold 0.6`. Scribe: `voice stt set vad_silence_threshold_secs 0.5`
- **"Stop cutting me off"** → Flux: raise `eot_threshold` (0.9) or `eot_timeout_ms`. Scribe: raise `vad_silence_threshold_secs`
- **"Stop when I talk over you" / "don't stop when I talk"** → `voice behavior set barge_in on` / `off`
- **"Use the other speech provider"** → `voice stt use <provider>` or `voice tts use <provider>`

## Provider notes

- **Deepgram Flux**: `flux-general-en` (~$0.0048/min); new accounts get $200 free credit. Key terms bias the transcription toward specific words (e.g. your name).
- **ElevenLabs Scribe**: takes 50 key terms of 20 characters or less, and a plan limits how many sessions run at the same time (6 on Free up to 45 on Scale). A session that the limit refuses ends with `stt_limit`.
- **ElevenLabs TTS**: ships with premade voices; users can also add custom or cloned voices from their ElevenLabs account. When the user provides a voice ID without a name or description, fetch them before `voice tts voices add`:
  ```bash
  curl -s https://api.elevenlabs.io/v1/voices/<id> | python3 -c "
  import sys,json; v=json.load(sys.stdin); l=v.get('labels',{})
  print(v.get('name',''))
  print(', '.join(p for p in [l.get('description',''),l.get('accent',''),l.get('gender','')] if p))"
  ```
  Use the first line as `--name` and the second as `--description`. If the fetch fails, ask the user.
- **Deepgram Aura-2**: the voice ID is the model name, `aura-2-<voice>-<language>`. One request takes 2000 characters, so a longer reply is split at sentence ends and joined. A voice that Deepgram adds later works with `voice tts voices add <model name> --name <name>`.

## Own providers

You can add a provider for any role: a different vendor, or a model that runs on this box. The engine sees a provider only through the protocol of its role in `cli/src/voice/providers/base.py` (`SttProvider`, `TtsProvider`, `Judge`), so nothing else changes.

1. Write `cli/src/voice/providers/<name>.py`. It implements the protocol of the role. The shipped providers beside it are working examples.
2. Add the provider to `cli/src/voice/providers/own.py`, in the map of its role, under a name no other provider of that role uses. A name used two times makes every `voice` command fail and say which one.
3. Add one row for the provider to the contract suite of its role (`cli/tests/test_stt_providers.py` or `cli/tests/test_tts_providers.py`), with a fake of its service, and run `uv run --project ~/agent/skills/voice/cli pytest ~/agent/skills/voice/cli/tests/`.
4. Run `voice <role> connect <name>`, then `voice daemon restart`.

Keep your provider in its own file and in `own.py`, and leave the shipped files as they are: an update merges new stock lines into those, and a local change there conflicts or breaks at each update.

**A provider with no key** declares `needs_key = False`. `connect` then takes no `--key`, and `validate` checks that the provider can work, for example that its local service answers. For an address or a model name, declare a setting of type `text` in `settings_schema()` with a default that works on this box, so `connect` works before anyone sets a value; change it with `voice <role> set <key> <value>`.

**What your provider must do:**

- **An STT provider decides the end of a turn.** It sends `committed` when the turn is over. A model with no turn detection needs a silence detector in its adapter.
- **A TTS provider makes every format it lists in `formats`.** The engine converts no audio. The app plays `mp3_44100` and `mp3_22050`, and `opus_48000` where its player decodes Ogg Opus, so a model that makes only PCM needs an encoder in its adapter.
- **A TTS provider states how to write for its voice.** `reply_hint` is one clause that reaches you in the `reply_hint` of each app message whose reply the app reads aloud while `tts` is on, for example that the voice performs text in square brackets and does not say it. A voice that says each character declares `reply_hint = ""`.
- **The model runs in its own process.** The adapter is a client of a local service, over HTTP or a socket, so the voice CLI gets no heavy dependency and the model cannot block the engine.
- **Speed is the provider's job.** The engine waits for nothing: a slow STT model gives late turns and a late barge-in, and a judge slower than about a second has no effect.

A judge that runs on this box keeps the live transcript on the box.

## A voice client of your own

A device, a room speaker, or a phone bridge that you build is a client of the engine socket, `GET /voice/session` on the voice service. It sends mic audio and the text to speak, and the engine decides turns, barge-in, and playback. [PROTOCOL.md](PROTOCOL.md) has every frame. The Vesta app (dictation and conversation) and a WhatsApp call are clients of the same socket.

Two more routes make audio with no session. `POST /tts/speak` with `{"text": ..., "format": "mp3" | "pcm"}` answers with the audio of one text (`mp3` is `mp3_44100` when the provider makes it, else `mp3_22050`), and the app reads a reply aloud through `/tts/prepare` and `/tts/stream/{id}?formats=...` when no session is open (`formats` names the play formats the player decodes, as in `start_session`, and the best one the provider makes plays; with none, the clip is `mp3`). `/stt/listen` serves older builds of the app only: do not build on it.

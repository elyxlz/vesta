# WhatsApp Setup

Everything the build needs (Go, whisper.cpp static libs, gcc, ffmpeg) ships in
the agent image. Setup is one idempotent script:

```bash
~/agent/skills/whatsapp/setup.sh
```

It links the launcher onto PATH, warms the build cache (compile errors surface
here), downloads the whisper voice-transcription model, adds the daemon line to
the restart skill, and starts the daemon. Re-run it any time; it only does
what's missing.

## Linking an account

**Before linking**, confirm the user is linking a DEDICATED WhatsApp account
for the assistant, not their personal one (a linked personal account means the
assistant reads and sends from their personal chats). No separate number yet?
Read [PHONE_NUMBER.md](PHONE_NUMBER.md) and guide them through getting one.

```bash
whatsapp link
```

Prints one shareable URL (public tunnel route, no token). The user opens it,
goes to WhatsApp > Settings > Linked Devices > Link a Device, and scans. The
page keeps the code current automatically, so there is no 20-second race. The
command waits and reports success.

Fallback, pairing code (when the user can't scan): `whatsapp link --phone '+E.164'`.
Confirm the echoed number is EXACTLY the one being linked, then send the user
the code: WhatsApp > Linked Devices > Link a Device > Link with phone number.

**Pairing is rate-limited (2 attempts/hour).** Repeated pairing attempts get
numbers flagged and banned by WhatsApp. If the limit trips, wait it out and
retry only with the user's explicit go-ahead.

**Right after linking**, history sync runs and the daemon locks stop/restart
for 5 minutes. Log lines like `can't send presence without PushName set` or a
brief websocket EOF in this window are NORMAL; touch nothing.

**Once linked, message the user first.** Send a short hello from the new line
so the thread lands on the user's phone and they can save the number. If their
number is already known (memory, contacts), do it without asking; otherwise ask
for it, then send:

```bash
whatsapp add-contact 'User Name' '+12025551234'
whatsapp send 'User Name' 'hey, Vesta here. this is my WhatsApp line, save me!'
```

Sending is fine during the sync window; only stop/restart is locked.

## Troubleshooting

- `whatsapp daemon status` is the one diagnostic: auth state, connection,
  sync-window lock, pairing attempts, whatsmeow version.
- Daemon won't start: run `whatsapp serve` in the foreground; the compile or
  serve error prints directly.
- Auth state `not_authenticated` after a restore/restart: the device session
  was lost; re-link (with the user's go-ahead) via `whatsapp link`.

## How transcription works

1. When a voice note arrives, the CLI downloads the audio via the WhatsApp media API
2. `ffmpeg` converts the OGG/Opus audio to 16kHz mono WAV
3. The built-in whisper.cpp bindings transcribe the audio to text
4. The transcription replaces the `[audio]` placeholder in the notification

All transcription runs in-process. Model path override: `WHISPER_MODEL` env var
(default `/usr/local/share/ggml-small.bin`, downloaded by setup.sh).

## Contact card support

When someone sends a WhatsApp contact card (vCard), it is parsed and stored as:

```
[Contact: Name - +phonenumber]
```

The phone number is extracted from the `TEL` field of the vCard. Use `list-received-contacts` to list all received contact cards:

```bash
whatsapp list-received-contacts
whatsapp list-received-contacts --to Alex --limit 10
```

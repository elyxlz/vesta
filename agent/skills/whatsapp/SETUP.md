# WhatsApp shared setup

Use this file for installation, method selection, recovery, and diagnostics. For
the actual account-linking procedure, read the one method guide selected below.

## Contents

- [Install once](#install-once)
- [Select one account method](#select-one-account-method)
- [Universal safety rules](#universal-safety-rules)
- [Status and recovery](#status-and-recovery)
- [Named instances](#named-instances)
- [Troubleshooting](#troubleshooting)
- [Transcription](#how-transcription-works)
- [Contact cards](#contact-card-support)

## Install once

Everything the build needs (Go, whisper.cpp static libraries, gcc, and ffmpeg)
ships in the agent image.

1. Run `~/agent/skills/whatsapp/setup.sh`. It links the launcher onto `PATH`,
   warms the build cache, downloads the transcription model, and starts the daemon.
   It is safe to re-run.
2. Add `whatsapp daemon start` on its own line inside the fenced block under
   `## Daemons` in `~/agent/skills/restart/SKILL.md`. This restores inbound
   notifications after a container restart.

## Select one account method

| Situation | Guide |
| --- | --- |
| Give a Vesta Cloud tenant a hosted WhatsApp account | [SETUP_VESTA_CLOUD.md](SETUP_VESTA_CLOUD.md) |
| Give a non-cloud agent a WhatsApp account from a self-hosted Double Tick service | [SETUP_DOUBLETICK_DIRECT.md](SETUP_DOUBLETICK_DIRECT.md) |
| Keep the user's own phone as the WhatsApp account, with their own carrier number | [SETUP_SELF_MANAGED.md](SETUP_SELF_MANAGED.md) |

These describe where the WhatsApp account comes from, not deployment location. A
self-hosted Double Tick account is self-hosted API access and never traverses Vesta
Cloud. Your own phone means the user's phone stays the WhatsApp account. Both Vesta
Cloud and a self-hosted Double Tick service hand the agent a ready headless WhatsApp
account to link a companion to.

## Universal safety rules

- Run `whatsapp status` before linking. If `linked:true`, do not pair again.
- If `connecting:true`, an existing QR or phone-code attempt is active. Wait for
  the user; never start another.
- Pairing is limited to two attempts per hour. A failure is not permission to
  retry-loop; report it and wait for explicit approval.
- For five minutes after a successful link, history sync locks daemon stop/restart.
  A brief websocket EOF or `can't send presence without PushName set` can be normal
  during this window. Do not bounce the daemon.
- Use a dedicated account for an assistant. Linking a personal account grants the
  assistant access to that account's chats.

## Status and recovery

`whatsapp status` is the primary diagnostic:

- `{"linked":true,"connected":true,"number":"+44..."}`: healthy.
- `{"linked":true,"connected":false,...}`: let the daemon reconnect; use the
  returned `next` only if it cannot.
- `{"linked":false,"connecting":true,...}`: wait for the active link attempt.
- `{"linked":false,"connected":false,"next":"run: whatsapp connect",...}`:
  for initial setup, run the selected method once; if a previous link was lost,
  request approval first.

`whatsapp daemon status` adds pairing-attempt and sync-lock details. Read
`~/agent/logs/whatsapp.log` for daemon output. Use `whatsapp daemon start` to
idempotently bring up a stopped daemon; do not run `whatsapp serve` in the
background or manage its process by hand.

## Named instances

Use `--instance <name>` when the box intentionally links more than one account.
Each instance has its own daemon, socket, device store, state, and notifications.
Keep the flag on setup and subsequent commands, for example:

```bash
whatsapp connect --instance personal
whatsapp status --instance personal
whatsapp messages --instance personal --limit 10
```

Start read-only or silent instances with the corresponding daemon flags; the
daemon persists them across its own restarts. Never point two instances at the
same account/device store.

## Troubleshooting

- A Double Tick account reports `provisioning`: wait for the stated delay, then repeat
  the same idempotent `whatsapp connect` command once.
- A Double Tick account reports `blocked`: Double Tick reports the WhatsApp
  failure; follow `next` for a fresh account.
- A Double Tick account reports `rate_limited`: wait out the cooldown in `reason`.
- A Double Tick companion cannot obtain or validate its residential proxy lease:
  stop. Do not pair or reconnect over unrelated direct egress.
- Auth state is gone after restore/restart: request approval before running the
  selected method's connect command again.

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

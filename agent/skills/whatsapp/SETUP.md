# WhatsApp shared setup

Installation, method selection, recovery, and diagnostics. For the actual linking
procedure, read the one method guide selected below.

## Install once

The build's dependencies (Go, whisper.cpp static libraries, gcc, ffmpeg) ship in
the agent image.

1. Run `~/agent/skills/whatsapp/setup.sh`. It links the launcher onto `PATH`,
   warms the build cache, downloads the transcription model, and starts the
   daemon. Safe to re-run.
2. Add `whatsapp daemon start` to your restart daemons, so inbound notifications
   survive a container restart. The `restart` skill owns that list.

## Select one account method

Work through this in order; do not ask the user anything you can determine
yourself. It is about where the account comes from, not where the agent runs. You
pick the source and pass it explicitly as `--source`; the CLI never guesses.

1. **Already linked?** `whatsapp status` returns `linked:true`. Use it and stop.
2. **Managed Vesta Cloud VM?** Run `vesta-cloud whoami`: `account:true` with
   `managed_infra:true` means this box is a vesta.run VM with a managed WhatsApp.
   Run `whatsapp connect --source vesta-cloud --opener '<text>'` straight away,
   silently, without asking or telling the user. See the
   [Vesta Cloud WhatsApp account](SETUP_VESTA_CLOUD.md) guide. (`account:true`
   without `managed_infra` is a connected self-hosted box: its managed WhatsApp
   opens only with an active paid membership, so continue below.)
3. **`DOUBLETICK_API_URL` and `DOUBLETICK_API_KEY` both set?** Run
   `whatsapp connect --source doubletick --opener '<text>'`. See the
   [Double Tick WhatsApp account](SETUP_DOUBLETICK.md) guide.
4. **Otherwise, ask the user** which they want:
   - **Double Tick**, a provisioning service that hands the agent a ready headless
     account: ask whether they have Double Tick credentials. When they do, get the
     API URL and key from them, then follow the
     [Double Tick WhatsApp account](SETUP_DOUBLETICK.md) guide.
   - Their own account: `whatsapp connect --source self-managed`. The user
     supplies a dedicated WhatsApp account on their own SIM (a second account on
     their phone, or a spare phone) and the agent links to it as a companion. See
     the [self-managed account](SETUP_SELF_MANAGED.md) guide.

## Status and recovery

`whatsapp status` is the primary diagnostic:

- `{"running":false,...}`: the daemon is down; start it with `whatsapp daemon start`.
- `{"linked":true,"connected":true,...}`: healthy.
- `{"linked":true,"connected":false,...}`: let the daemon reconnect; use the
  returned `next` only if it cannot.
- `{"linked":false,"connecting":true,...}`: wait for the active link attempt.
- `{"linked":false,"connected":false,"next":"run: whatsapp connect --source ...",...}`: for
  first setup, run the selected method once; if a prior link was lost, get
  approval first (see the [linking rule](SKILL.md#the-linking-rule)).

`whatsapp daemon status` adds pairing-attempt and sync-lock detail;
`~/agent/logs/whatsapp.log` has daemon output. No command starts the daemon for you.
Use `whatsapp daemon start` to bring up a stopped one. Never run `whatsapp serve` by hand.

A headless (Vesta Cloud or Double Tick) `whatsapp connect` returns a terminal
status. Handle each:

- `provisioning`: wait the stated delay, then repeat the same `whatsapp connect` once.
- `blocked`: Double Tick found the WhatsApp account unusable; follow `next` for a
  fresh account.
- `rate_limited`: wait out the cooldown in `reason`; never retry-loop or generate
  extra pair codes.
- logged out after a prior link, or auth state gone after a restore/restart: get
  approval, then repeat the same connect once.
- companion cannot obtain or validate its
  [residential proxy lease](HEADLESS.md#residential-proxy-lease): stop; do not
  pair or reconnect over direct egress.

## Named instances

Use `--instance <name>` when the box intentionally links more than one account.
Each instance has its own daemon, socket, device store, state, and notifications.
Keep the flag on every command:

```bash
whatsapp connect --source self-managed --instance personal
whatsapp status --instance personal
whatsapp messages --instance personal --limit 10
```

For a read-only or silent instance, start its daemon with the flag BEFORE the first
connect:

```bash
whatsapp daemon start --instance personal --read-only
whatsapp connect --source self-managed --instance personal
```

`--read-only` blocks sending, receipts, and presence; `--no-notifications` silences
notifications. `whatsapp connect` requires a running daemon, so it links through the daemon you
started and the flag stays in force. A later `whatsapp daemon start` that omits the flag replays it
from the recorded run, so the instance comes back read-only. Keep the flag on that instance's
`whatsapp daemon start` line in your restart daemons so it survives every restart. Never point two
instances at the same account/device store.

## Operational notes

- For five minutes after a successful link, history sync locks daemon
  stop/restart. A brief websocket EOF is normal in this window; do not bounce the
  daemon.
- `can't send presence without PushName set` is only transient inside that window.
  **Past it, the same line means the push name was never set, so the account never
  shows online.** That is the whole effect. Read receipts and typing both survive it:
  `SendChatPresence` has no push-name check, and a presence failure is deliberately
  kept from suppressing the read receipt (`events.go`, pinned by
  `TestReadReceiptSurvivesPresenceFailure`). Nothing else reports the problem and the
  only symptom is that one warning repeating, so it reads as known noise and gets
  dismissed indefinitely.
  Fix it with `whatsapp set-profile-name "<name>"`, which sets the local push name
  presence actually requires. The account-wide leg needs app-state keys a fresh
  headless number usually lacks and is skipped with a warning; that skip is fine and
  is not the failure. Confirm from the log that the call did **not** warn
  `broadcasting presence failed`.
- Use a dedicated account for the assistant. Linking a personal account grants it
  access to that account's chats.

## Transcription

Voice notes transcribe in-process: the CLI downloads the audio, `ffmpeg` converts
it to 16kHz mono WAV, and the built-in whisper.cpp bindings replace the `[audio]`
placeholder with the text. Override the model path with the `WHISPER_MODEL` env
var (default `/usr/local/share/ggml-small.bin`, downloaded by `setup.sh`). Set
`WHISPER_LANGUAGE` to a whisper.cpp language code (default: auto-detect) when the
user's voice notes are one known language, since auto-detection can misread short clips.

## Contact cards

A received WhatsApp contact card (vCard) is parsed and stored, taking the number
from the vCard `TEL` field, as:

```
[Contact: Name - +phonenumber]
```

List received cards with `whatsapp list-received-contacts [--to <name>] [--limit N]`.

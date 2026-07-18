---
name: whatsapp
description: WhatsApp messages, contacts, groups, and live voice calls (place/answer, talk in your own voice; not generic text/SMS). Use to message or call someone on WhatsApp.
---

# WhatsApp (CLI: `whatsapp`)

You never stop or restart anything, and you don't manage the daemon by hand. The
`whatsapp` CLI runs its own background daemon: the restart skill runs `whatsapp
start` at boot to bring it up (so inbound WhatsApp notifications flow before you
send anything), and every command below also brings it up on demand. Your whole
world is four verbs: **connect, status, send, messages** (plus profile and calls).

## The one rule

**If `whatsapp status` ever shows `linked: false`, run `whatsapp connect`.**
That is the only recovery you ever need. Never re-link, re-pair, or "restart the
daemon" any other way; connect is idempotent and safe to re-run.

## Set up (one command)

`whatsapp connect` is the single setup verb. It picks the right path for the box on
its own, so you never choose between modes. Every output carries a `next:` step, so
just do what it says:

- **Hosted (vesta.run) box:** it claims the agent's own managed number and links
  it, returning `{status:"linked", number, next:...}`. Follow `next`: share the
  number and its `wa.me` link so the user messages you FIRST (reply-first: never
  cold-initiate), then reply only once they do.
- **Still filling:** `{status:"provisioning", next:...}` means the number is still
  being set up. Re-run `whatsapp connect` in about 30 seconds; repeating is safe.
- **Blocked:** `{status:"blocked", next:...}` means that number was banned. Re-run
  `whatsapp connect` to get a fresh one.
- **Self-hosted (user's own WhatsApp):** it serves a QR page and returns
  `{status:"linking", url, next:...}`. Send the user the URL to scan in WhatsApp >
  Settings > Linked Devices. See [SETUP.md](SETUP.md) / [MANAGED_AUTH.md](MANAGED_AUTH.md).

## Check state

`whatsapp status` is your one diagnostic:
- linked: `{"linked":true,"number":"+44...","connected":true}`
- not linked: `{"linked":false,"connected":false,"next":"run: whatsapp connect","reason":"<why>"}`

## Send

```bash
whatsapp send --to 'Alice' --message 'Hi'          # positionals also work: whatsapp send Alice 'Hi'
whatsapp send --to 'Alice' --message 'reply' --reply-to '<message_id>'   # quote a message
```
- `--to` accepts a contact name, phone (`+E.164`), group name, or JID; the CLI resolves it.
- Prefer `--message-file <path>` (or `--message -` / `--message-file -` for stdin) when the
  text has apostrophes, quotes, backticks, `$(...)`, or multiple lines, so the shell can't mangle it.
- Short bubbles only: a wall (over ~220 chars, or 3+ sentences in one bubble) is rejected.
  Re-send as several short calls, one thought each. Pass `--longform` only for genuine
  reference material the user asked for (a brief, a code block, a list).
- Before texting an unknown raw number, save it first with `add-contact` (name + phone).

## Read

- `whatsapp messages [--to <name>] [--query <text>] [--after <RFC3339>] [--limit N]` reads the local DB.
- `whatsapp chats`, `whatsapp contacts`, `whatsapp groups` list the obvious things.
- `whatsapp backfill --to <name>` asks the phone for older history when the local DB is thin.
- `whatsapp check-delivery --message-id <id>` (or `--recent`) checks whether a send landed.
- Message IDs come from inbound notification payloads (`message_id`) or `messages` output.

## Profile

Change the agent's own WhatsApp name/picture from its own client (no phone, no QR, works while linked):
- `whatsapp profile name 'mozzy'` sets the display (push) name. Account-wide and immediate, but a
  contact keeps seeing the OLD name until you next message them, so message them once to refresh it.
- `whatsapp profile photo ~/avatar.jpg` sets the picture. JPEG (PNG is auto-converted), roughly square (~640x640).

## Edited and deleted messages

People change their minds after they hit send, so a message you already read can change or vanish:

- **An edit** arrives as an `edit` notification whose body carries what the message says now, just like a plain message, naming the message that changed (`target_message_id`) and the text you last saw (`old_text`). The stored message is rewritten, so `list-messages` and search show only the new text. Answer again only if the edit asks something new: a fixed typo needs nothing from you.
- **A deletion** (delete-for-everyone) arrives as a `revoke` notification with the text you last saw in `old_text`. They took it back, so treat it as unsaid and do not quote it at them.

## Voice calls

Hold a live call in your own voice (the `voice` skill's TTS) and hear the other person (its STT):
- The other person's speech arrives as `call_utterance` notifications; it interrupts like any message,
  so you answer live by **speaking** with `whatsapp say '<one short line>'` (one spoken thought at a
  time, not a monologue). A newer `say` replaces whatever is still playing.
- `whatsapp call --to <name>` places a call and returns once answered; greet them with `say`.
  Inbound calls answer automatically. `whatsapp hangup` ends it; `whatsapp call-status` reports the active call.
- Requires the `voice` skill with both STT and TTS; without it, calls are declined and you are told to set it up.
- **Calling is your loudest, most interrupting reach.** Reserve `whatsapp call` for the genuinely
  time-critical (a real deadline, a safety or money issue, something they asked to be called about)
  and only after messages went unanswered. Respect anything the constitution says about calling.

## More commands

`whatsapp` with no args lists everything. Others (all take `--help`): `send-file`, `send-audio`,
`react`, `revoke-message`, `download-media`, `create-group`, `leave-group`, `rename-group`,
`set-group-description`, `set-group-photo`, `get-group-invite-link`, `update-group-participants`,
`archive-chat`, `delete-chat`, `remove-contact`.

## Rules

- **Send one WhatsApp call at a time.** Never batch sends (or `say` lines) in a parallel tool-call
  block: if one fails you can't tell which landed, and a retry sends a duplicate; parallel `say` lines race.
- **Never re-link without the user's explicit go-ahead.** Pairing is rate-limited because repeated
  attempts get numbers flagged and banned. If linking fails, report it and wait; don't retry-loop.
- Phone numbers are E.164 with a leading `+` (e.g. `+12025551234`). Auth state lives in `~/.whatsapp/`.

Advanced setup (second/personal account, read-only, silent instances) and how to develop the CLI:
see [SETUP.md](SETUP.md) and [DEVELOPING.md](DEVELOPING.md).

## Contact Preferences
[How the user prefers to communicate with different contacts]

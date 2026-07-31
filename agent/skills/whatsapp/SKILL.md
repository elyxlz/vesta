---
name: whatsapp
description: Set up and operate WhatsApp accounts, messages, contacts, groups, and live voice calls (not generic text/SMS). Use when linking WhatsApp, acquiring a Vesta Switchboard number, choosing Vesta Cloud, direct Double Tick, or self-managed setup, or messaging or calling someone on WhatsApp.
---

# WhatsApp (CLI: `whatsapp`)

Every `whatsapp` command starts the daemon on demand, and the restart skill runs
`whatsapp daemon start` at boot to bring it up (so inbound WhatsApp notifications
flow before you send anything), so let it manage itself: your whole world is four
verbs: **connect, status, send, messages** (plus profile and calls).

## The linking rule

Always start with `whatsapp status`. If `linked: true`, use the existing link. If
`connecting: true`, wait for that attempt and do not start another. If this is a
first-time setup and `linked: false`, run the selected `whatsapp connect` method.
If a previously linked account was logged out or lost, get the user's approval
before running it. Never recover by manually re-pairing or restarting the daemon.

## Choose the setup method

`whatsapp connect` is the single setup verb, but there are three ownership and
transport arrangements. Determine the method from the environment and the user's
ownership choice, then read exactly that guide before the first link:

| Method | Primary device | API route | Command | Detailed guide |
| --- | --- | --- | --- | --- |
| Vesta Cloud-managed number | Headless Double Tick primary | Vesta Cloud coordinates Switchboard for the number/SMS and Double Tick for WhatsApp | `whatsapp connect --opener '<text>'` | [SETUP_VESTA_CLOUD.md](SETUP_VESTA_CLOUD.md) |
| Direct Double Tick-managed number | Headless Double Tick primary | Agent calls Double Tick directly; the operator configures a separate number provider | `whatsapp connect --opener '<text>'` | [SETUP_DOUBLETICK_DIRECT.md](SETUP_DOUBLETICK_DIRECT.md) |
| Self-managed WhatsApp account | User's phone | None (the user brings their own WhatsApp number) | `whatsapp connect` or `--phone` | [SETUP_SELF_MANAGED.md](SETUP_SELF_MANAGED.md) |

Do not infer ownership from where the agent runs. A self-hosted agent with
`DOUBLETICK_API_URL` and `DOUBLETICK_API_KEY` uses Direct Double Tick; it does not
use Vesta Cloud.

Selection order is deterministic: an existing linked device resumes; otherwise
complete direct Double Tick credentials select the direct headless path, a Vesta
Cloud tenant selects the cloud-managed path, and everything else uses self-managed
QR or phone pairing. Do not manually choose an internal subcommand.

For either headless Double Tick method, the companion's WhatsApp socket must use
the residential proxy lease for the bound primary on initial pairing and every
reconnect. API requests still use the direct or cloud route shown above; the proxy
only carries WhatsApp traffic. If the lease cannot be obtained or verified, stop
and report the error rather than falling back to unrelated direct egress.

All agent-dedicated numbers backed by headless Double Tick primaries are
reply-first. Compose a warm opener in your own voice from the user's perspective,
pass it with `--opener`, share the returned `wa.me` link, and wait for the user to
message first. User-owned phone-primary methods use normal messaging rules.

Shared installation, restart wiring, statuses, and diagnostics live in
[SETUP.md](SETUP.md). Switchboard, Double Tick, and authentication boundaries live in
[MANAGED_AUTH.md](MANAGED_AUTH.md).

Common managed-number outcomes:

- `{"status":"linked","number":"+44...","next":"..."}`: follow `next`.
- `{"status":"provisioning","next":"..."}`: re-run `whatsapp connect` after the stated delay.
- `{"status":"blocked","next":"..."}`: Double Tick found the WhatsApp account
  unusable; follow `next` (Vesta Cloud releases and reserves a fresh number).
- `{"status":"rate_limited","reason":"...","next":"..."}`: wait out the named cooldown. Never retry-loop.

## Check state

`whatsapp status` is your one diagnostic:
- linked: `{"linked":true,"number":"+44...","connected":true}`
- connecting: `{"linked":false,"connecting":true,"method":"qr","next":"wait for the user to scan..."}`
- pairing code active: `{"linked":false,"connecting":true,"method":"phone","next":"wait for the user to enter..."}`
- not linked: `{"linked":false,"connected":false,"next":"run: whatsapp connect","reason":"<why>"}`

## Send
- Form: `whatsapp <subcommand> [positionals] [--flag value ...]`. **Subcommand goes first**, before any flags.
- Most common subcommands accept leading positional args that the CLI rewrites into flags (e.g. `whatsapp send 'Alice' 'Hi'` is identical to `whatsapp send --to 'Alice' --message 'Hi'`). You can always use the flag form.
- Flags for a specific subcommand: `whatsapp <subcommand> --help`. The top-level `whatsapp` with no args prints the command list.
- Names for `--to` / `--chat-id` / `--group`: contact name, phone (`+E.164`), group name, or JID; the CLI resolves them.
- Send every message body through `--message -` and a quoted heredoc, as in the example below. The shell expands nothing inside `<<'MSG'`, so apostrophes, quotes, backticks, `$(...)` and newlines all pass through untouched. An inline `--message 'text'` breaks on the first apostrophe, so use it only for text you can see has none.
- `send-message` enforces short-bubble texting: a wall (over ~220 chars, or any text after a full stop) is rejected so you re-send as several short calls, one thought each. Don't use full stops at all: a `.`, `!` or `?` may only close a bubble, never carry text after it. Ellipses stay free, they're a beat rather than a stop. For genuine reference material the user asked for (a brief, a code block, a list), pass `--longform` to bypass. This applies to heredoc sends too, so `--longform` is the only escape hatch.
- A numbered or bulleted list is fine to send as one message (each item is one short thought); a line-leading marker like `1.` or `2)` is not a full stop, so a list does not need `--longform`.

```bash
# The one shape to use for any message body. Replace only the middle line.
whatsapp send --to 'Alice' --message - <<'MSG'
can't wait to see you
MSG

whatsapp send --to 'Alice' --message - --reply-to '<message_id>' <<'MSG'   # quote a message
same here
MSG
```
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

Shared setup and named-instance details: [SETUP.md](SETUP.md). CLI development:
[DEVELOPING.md](DEVELOPING.md).

## Contact Preferences
[How the user prefers to communicate with different contacts]

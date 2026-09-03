---
name: whatsapp
description: Set up and operate WhatsApp accounts, messages, contacts, groups, and live voice calls (not generic text/SMS). Use when linking WhatsApp, choosing a Vesta Cloud WhatsApp account, a Double Tick WhatsApp account, or a self-managed account, or messaging or calling someone on WhatsApp.
---

# WhatsApp (CLI: `whatsapp`)

The restart skill runs `whatsapp daemon start` at boot, so inbound notifications flow
before you send anything. A command never starts the daemon for you, so a stopped
account stays down until you start it on purpose. Your whole world is four verbs:
**connect, status, send, messages** (plus profile and calls).

## The linking rule

Always start with `whatsapp status`:

- `{"running":false,...}`: the daemon is down; start it with `whatsapp daemon start`, unless you are deliberately holding this account offline.
- `{"linked":true,...}`: use the existing link, do not pair again.
- `{"linked":false,"connecting":true,...}`: an attempt is active; wait for it (follow `next`), never start another.
- `{"linked":false,"connected":false,...}` on first-time setup: run the selected `whatsapp connect` method.
- linked earlier, now logged out or lost: get the user's explicit approval before reconnecting.
  On a managed number a re-link also drops outbound to everyone who has not messaged you since,
  and only their next inbound restores it, so an unasked reconnect can cost the channel to the one
  person who matters, at the moment you most need it.

Never recover by manually re-pairing or restarting the daemon.

## Holding an account offline

When the provider flags, suspends, or reviews a number, that account must make no
connection attempt until they clear it:

```bash
whatsapp daemon stop --instance <name>
```

Then remove that account's `whatsapp daemon start` line from your restart daemons (the
`restart` skill owns that list), so no boot brings it back. To return it once the provider
clears it, add the line again and run `whatsapp daemon start --instance <name>`.

## Choose the setup method

`whatsapp connect` is the one setup verb, and `--source` is required: you state the
account source, the CLI never guesses. [SETUP.md](SETUP.md) has the decision flow
that picks the source from the environment and the user's choice; read the matching
guide before the first link.

| Account source | Command | Guide |
| --- | --- | --- |
| Vesta Cloud WhatsApp account | `whatsapp connect --source vesta-cloud --opener '<text>'` | [SETUP_VESTA_CLOUD.md](SETUP_VESTA_CLOUD.md) |
| Double Tick WhatsApp account | `whatsapp connect --source doubletick --opener '<text>'` | [SETUP_DOUBLETICK.md](SETUP_DOUBLETICK.md) |
| Self-managed account | `whatsapp connect --source self-managed` (or `--phone`) | [SETUP_SELF_MANAGED.md](SETUP_SELF_MANAGED.md) |

A Vesta Cloud or Double Tick account is headless and **reply-first**: compose a
warm opener in your own voice from the user's perspective, pass it with
`--opener`, share the returned `wa.me` link, and wait for the user to message
first. A self-managed account uses normal messaging rules.

Recovery outcomes and diagnostics live in [SETUP.md](SETUP.md#status-and-recovery);
the residential proxy-lease rule lives in [HEADLESS.md](HEADLESS.md).

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
- Before texting an unknown raw number, save it first with `add-contact` (name + phone). A chat WhatsApp shows only as an id (`...@lid`) has no number to save, so save it by that id instead: `add-contact --name <name> --chat <chat_jid>`.
- Give each contact a distinct name. `add-contact` refuses a name another number already holds, so a saved name always points at one person and a reply can address them by name. When it refuses, pick a name that tells them apart (e.g. `Emmy R`).

**Error 463, `no signal session for this device yet`.** The send fails for one recipient while
everyone else succeeds on the same number and daemon, so it looks like local state you can repair.
It usually is not. Make one further attempt at most, then say what you need to say on another
channel; it clears by itself the moment that person sends you anything.

**Never re-pair or restart the daemon to chase it.** Pairing is hard-capped per day and per week,
and repeat pairing is what gets numbers banned.

Rule out the local store without sending anything, since the obvious comparison test (message some
other contact and see) is unavailable: cold-initiating anyone who has not written first is the
behaviour that gets a fresh number banned.

```bash
python3 -c 'import sqlite3, pathlib; print(*sqlite3.connect(pathlib.Path.home() / ".whatsapp/whatsapp.db").execute("select their_id from whatsmeow_sessions").fetchall(), sep="\n")'
```

Rows are `<lid>_1:<device>`, one per device that recipient uses. Rows present for them means this
is not a missing-session problem, so stop looking there.

**On a managed number (Vesta Cloud, Double Tick) it is not yours to fix.** The prekey fetch for a
device you hold no session for happens in the provider's infrastructure rather than in your client,
so two agents holding an identical device set for the same recipient can get opposite results.
Falling back to another channel is the entire remedy available to you.

Pick the fallback channel by their last inbound there, never by your own last outbound: a channel
whose recent traffic is all yours is dead, and silence from it reads exactly like an answer. Read
it with that channel's own command (`telegram messages --to <name>`, `app-chat history`) first.

## Read

- `whatsapp messages [--to <name>] [--query <text>] [--after <RFC3339>] [--limit N]` reads the local DB.
- `whatsapp chats`, `whatsapp contacts`, `whatsapp groups` list the obvious things.
- `whatsapp backfill --to <name>` asks the phone for older history when the local DB is thin.
- `whatsapp check-delivery --message-id <id>` (or `--recent`) checks whether a send landed.
- Message IDs come from inbound notification payloads (`message_id`) or `messages` output.
- **One direct chat is stored under two keys** (the peer's phone JID and their LID). `messages --to`
  reads both; hand-written SQL against `messages.db` gets one side, which reads as "they never
  replied" rather than as missing data. Prefer the command.
- The one residual split: a LID whatsmeow holds no phone mapping for stands alone, so
  `messages --to <name>` can look outbound-only for that contact and `backfill` will not change it
  (nothing is missing, the inbound half is filed under the unmapped id). Before reading a silence as
  real, sum both directions per chat id in `~/.whatsapp/messages.db` (python3's sqlite3 module, as
  in the 463 section): `SELECT chat_jid, SUM(is_from_me=0), SUM(is_from_me=1), MAX(timestamp) FROM
  messages GROUP BY chat_jid` shows a split identity at a glance. Group chats (`<id>@g.us`) hold a
  third slice of the same relationship, so include them when computing "last heard from".

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
- Success JSON prints on stdout; any failure exits non-zero and prints its error on stderr, so it
  survives piping stdout through `grep`, `head`, or `jq`.
- **Never re-link without the user's explicit go-ahead** (the linking rule). Pairing is rate-limited to
  about two attempts per hour because repeated attempts get accounts flagged and banned; if linking
  fails, report it and wait, never retry-loop.
- Phone numbers are E.164 with a leading `+` (e.g. `+12025551234`). Auth state lives in `~/.whatsapp/`.

Shared setup and named-instance details: [SETUP.md](SETUP.md).

## Contact Preferences
[How the user prefers to communicate with different contacts]

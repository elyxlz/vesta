---
name: whatsapp
description: Set up and operate WhatsApp accounts, messages, contacts, groups, and live voice calls (not generic text/SMS). Use when linking WhatsApp, choosing a Vesta Cloud WhatsApp account, a Double Tick WhatsApp account, or a self-managed account, or messaging or calling someone on WhatsApp.
---

# WhatsApp (CLI: `whatsapp`)

Every `whatsapp` command starts the daemon on demand, and the restart skill runs
`whatsapp daemon start` at boot (so inbound notifications flow before you send
anything), so let it manage itself. Your whole world is four verbs: **connect,
status, send, messages** (plus profile and calls).

## The linking rule

Always start with `whatsapp status`:

- `{"linked":true,...}`: use the existing link, do not pair again.
- `{"linked":false,"connecting":true,...}`: an attempt is active; wait for it (follow `next`), never start another.
- `{"linked":false,"connected":false,...}` on first-time setup: run the selected `whatsapp connect` method.
- previously linked, now logged out or lost: get the user's explicit approval before reconnecting.

Never recover by manually re-pairing or restarting the daemon.

## Choose the setup method

`whatsapp connect` is the one setup verb, and `--source` is required: you state the
account source, the CLI never guesses. [SETUP.md](SETUP.md) has the decision flow
that picks the source from the environment and the user's choice; read the matching
guide before the first link.

| Account source | Command | Guide |
| --- | --- | --- |
| Vesta Cloud WhatsApp account | `whatsapp connect --source cloud --opener '<text>'` | [SETUP_VESTA_CLOUD.md](SETUP_VESTA_CLOUD.md) |
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
- Before texting an unknown raw number, save it first with `add-contact` (name + phone).

## Read

- `whatsapp messages [--to <name>] [--query <text>] [--after <RFC3339>] [--limit N]` reads the local DB.
- `whatsapp chats`, `whatsapp contacts`, `whatsapp groups` list the obvious things.
- `whatsapp backfill --to <name>` asks the phone for older history when the local DB is thin.
- `whatsapp check-delivery --message-id <id>` (or `--recent`) checks whether a send landed.
- Message IDs come from inbound notification payloads (`message_id`) or `messages` output.

### One person can occupy TWO chats, and this makes reads look outbound-only

WhatsApp may deliver a contact's **inbound** messages under a linked-device id (`<digits>@lid`)
while your **outbound** replies are stored under their phone JID (`<number>@s.whatsapp.net`).
The local DB then holds one conversation as two separate chats, and `messages --to <name>`
resolves the NAME to the phone JID, so it can return almost nothing but your own messages.

This is easy to misread as a sync problem. It is not, and `backfill` will not change it, because
nothing is missing: the inbound half is simply filed under the other id.

The symptom is quiet, and it corrupts your model of the relationship rather than throwing an
error. "They have not replied in a few hours" and "they have not replied in weeks" look identical
if you only ever query one id.

To ask **when someone last wrote**, or **how many messages you have sent into their silence**,
query every id belonging to them rather than the contact name. This query makes a split identity
obvious at a glance:

```sql
SELECT chat_jid,
       SUM(CASE WHEN is_from_me=0 THEN 1 ELSE 0 END) AS inbound,
       SUM(CASE WHEN is_from_me=1 THEN 1 ELSE 0 END) AS outbound,
       MAX(timestamp) AS last_activity
FROM messages GROUP BY chat_jid ORDER BY last_activity DESC;
```

A chat showing `inbound=N, outbound=0` beside another showing `inbound=0, outbound=M` is one
person split across two ids. Group chats (`<id>@g.us`) hold a third slice of the same
relationship, so include them when computing "last heard from".

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
- **Never re-link without the user's explicit go-ahead** (the linking rule). Pairing is rate-limited to
  about two attempts per hour because repeated attempts get accounts flagged and banned; if linking
  fails, report it and wait, never retry-loop.
- Phone numbers are E.164 with a leading `+` (e.g. `+12025551234`). Auth state lives in `~/.whatsapp/`.

Shared setup and named-instance details: [SETUP.md](SETUP.md).

## Contact Preferences
[How the user prefers to communicate with different contacts]

---
name: whatsapp
description: WhatsApp messages, contacts, groups, and live voice calls (place/answer, talk in your own voice; not generic text/message). Requires whatsapp daemon.
---

# WhatsApp - CLI: `whatsapp`

**Setup / linking**: run `~/agent/skills/whatsapp/setup.sh`, then `whatsapp link`, and once linked message the user first so they have the new number; see [SETUP.md](SETUP.md).
**Daemon**: `whatsapp daemon start|stop|restart|status` (start is idempotent and safe to re-run; status is the one diagnostic).

## Calling the CLI

- Form: `whatsapp <subcommand> [positionals] [--flag value ...]`. **Subcommand goes first**, before any flags.
- Most common subcommands accept leading positional args that the CLI rewrites into flags (e.g. `whatsapp send 'Alice' 'Hi'` is identical to `whatsapp send --to 'Alice' --message 'Hi'`). You can always use the flag form.
- Flags for a specific subcommand: `whatsapp <subcommand> --help`. The top-level `whatsapp` with no args prints the command list.
- Names for `--to` / `--chat-id` / `--group`: contact name, phone (`+E.164`), group name, or JID - the CLI resolves them.
- For `send-message`, prefer `--message-file <path>` (or `--message-file -` / `--message -` to read from stdin) when the body contains apostrophes, quotes, backticks, `$(...)`, or multiple lines: an inline `--message 'text'` lets the shell mangle or even evaluate it.
- `send-message` enforces short-bubble texting: a wall (over ~220 chars, or 3+ sentences in one bubble) is rejected so you re-send as several short calls, one thought each. For genuine reference material the user asked for (a brief, a code block, a list), pass `--longform` to bypass. This applies to `--message-file` sends too, so `--longform` is the only escape hatch.

## Reply / Quote
```bash
whatsapp send --to 'Name' --message 'reply text' --reply-to '<message_id>'
```
The `--reply-to` flag quotes the referenced message in WhatsApp's native reply UI. The message ID can be found in incoming notification payloads (`message_id` field) or `list-messages` output.

## Voice calls

You can hold a live voice call over WhatsApp, in your own voice (the `voice` skill's TTS), and hear the other person (the same skill's STT):

- **Being on a call.** Everything the other person says arrives as a `call_utterance` notification with their transcript and who they are; it interrupts like any WhatsApp message, so you respond live. You reply by **speaking**, with `whatsapp say`, one short spoken line per call (the same short-bubble instinct as texting, not a monologue). `say` replaces whatever is still playing, so your newest line always wins, and the other person talking over you cuts your current line short. When you place a call, `whatsapp call` returns once they answer, that is your cue to greet them with `say`.
- **Inbound calls** are answered automatically (you get a `call_started`, then their utterances). A call you cannot take (already on another call, or `voice` not set up) becomes a `call_missed` notification instead. `call_ended` closes the loop.
- **Requires the `voice` skill** configured with both input (STT) and output (TTS). Without it, calls are declined and you are told to set voice up.

**Calling the user when it is urgent.** A call is your loudest, most interrupting reach, so it is rare and reserved for the genuinely time-critical. If something truly needs the user now (a real deadline about to pass, a safety or money issue, something they explicitly asked to be called about) and they have not responded to your messages within a window that fits how urgent it is, `whatsapp call` them and say why in one line. Do not call for anything that can wait for a text, and respect anything the constitution says about calling.

## Commands

Aliases in parentheses. Positional signature shown after `:` for commands that take positionals.

**Sending**
- `send-message` (`send`) : `<to> <message>`
- `send-file` (`file`) : `<to> <file-path>`
- `send-audio` - voice note; use `--help` for flags
- `send-reaction` (`react`) : `<to> <message-id> <emoji>`
- `revoke-message` - unsend; `--to <to> --message-id <id>`
- `download-media` - `--to <to> --message-id <id>`; saves to `~/.whatsapp/downloads/`

**Reading**
- `list-chats` (`chats`)
- `list-messages` (`messages`) : `<to>` - local DB only
- `list-contacts` (`contacts`, `search-contacts`)
- `list-groups` (`groups`)
- `list-received-contacts` - contact cards (vCards) received from others
- `check-delivery` (`delivery`) : `<message-id>`
- `backfill` : `<to>` - asks the phone for older history

**Contacts**
- `add-contact` : `<name> <phone>`
- `remove-contact` : `<identifier>` (name or phone)

**Groups**
- `create-group` - `--help` for flags
- `leave-group` : `<group>`
- `rename-group` (`rename`) : `<group> <name>`
- `set-group-description` : `<group> <description>`
- `set-group-photo` - `--help` for flags
- `get-group-invite-link` - `--help` for flags
- `update-group-participants` - add/remove members; `--help` for flags

**Calling** (live voice calls)
- `call` : `<to>` - place a live voice call. Blocks until answered, declined, or times out, then returns the outcome.
- `say` : `<text>` - speak a line into the active call (prefer `--text-file` / `--text -` for lines with apostrophes or quotes)
- `hangup` - end the active call
- `call-status` - report the active call, or idle

**Chat management**
- `archive-chat` : `<to>`
- `archive-all-chats`
- `delete-chat` : `<to>`
- `clear-all-chats` - destructive; wipes local message DB

**Auth / daemon** (see SETUP.md for details)
- `daemon start|stop|restart|status` - manage the background daemon; `stop`/`restart` refuse during the 5-minute post-link sync window because restarting there logs the device out (`--force` overrides, at the cost of a re-pair)
- `link` - link an account: serves a self-refreshing public QR page and prints its URL; `--phone '+E.164'` for a pairing code instead. Rate-limited to 2 attempts/hour (`--acknowledge-ban-risk` overrides)
- `serve` - runs the daemon in the foreground (what `daemon start` and `link` launch under the hood); flags below
- `authenticate` - prints auth status

### `serve` flags

- `--notifications-dir <dir>` (optional, defaults to `~/agent/notifications`): directory where inbound notification JSON files are written for the agent to pick up.
- `--no-notifications` (optional): the daemon writes no notification files at all, so the agent receives nothing from this instance. Inbound messages are still stored locally and queryable on demand. Use for a passive linked account you want to read but never be pinged about.
- `--instance <name>` (optional): run a second, isolated account/session. State lives in `~/.whatsapp/<name>/` instead of `~/.whatsapp/`. This is how you link a second WhatsApp account (e.g. a personal account) alongside the agent's own line.
- `--read-only` (optional): passive mode. Blocks every write command (`send-message`, `send-file`, `send-audio`, `send-reaction`, `revoke-message`, `add-contact`, `remove-contact`, all group ops, `archive-chat`, `archive-all-chats`, `delete-chat`, `clear-all-chats`); each returns `command "X" blocked: instance is read-only`. Suppresses delayed read receipts (incoming messages are NOT marked read, no blue ticks) AND suppresses presence: `EnsureOnline()` is a no-op under read-only, so the account never broadcasts `available` and does not appear online to contacts. Read-only alone does NOT stop notifications; use `--no-notifications` or `--skip-senders` for that.
- `--skip-senders <phone,phone,...>` (optional): comma-separated E.164 numbers whose inbound messages never generate a notification. Messages are still stored and queryable, just silent.

**Recipe: link a personal account fully silently (passive, invisible to contacts).**
```bash
whatsapp serve --instance personal --read-only --no-notifications
```
The agent can read/search that account on demand (`whatsapp list-chats --instance personal`, `list-messages`, `search-contacts`, etc.) but receives zero notifications, never sends or marks-read, and the account never shows online to its contacts. Link it with `whatsapp link --instance personal`.

## Rules

- **Send one tool call at a time. Never batch WhatsApp sends (or `say` lines) in a single parallel tool-call block.**
  *Why:* If one parallel call fails while another succeeds, you can't tell which went through. Retrying "the failed one" sends a duplicate that the recipient sees. For `say`, parallel lines also race to play over each other.

- **Manage the daemon only through `whatsapp daemon ...`** (never raw `screen` or signals).

- **Never re-link / re-pair without the user's explicit go-ahead.** Pairing is rate-limited because repeated attempts get WhatsApp numbers flagged and banned. If linking fails, report it and wait; don't retry-loop.

- **Before sending to an unknown phone number, save it first with `add-contact`.**
  *Why:* Sending to a raw JID with no saved contact row triggers the `requireManualContact` guard and blocks the send.

- **Never `go build` a static whatsapp binary or run one directly.** `whatsapp` must stay the launcher symlink (`~/.local/bin/whatsapp` -> `~/agent/skills/whatsapp/whatsapp`), which compiles from source on every invocation and updates whatsmeow at daemon start.
  *Why:* A frozen binary silently drifts from the source as fixes land (issue #1073), and stale whatsmeow protocol code is what WhatsApp breaks and bans.

## Conventions

- Phone numbers: E.164 with leading `+` (e.g. `+12025551234`).
- JIDs: direct chats end in `@s.whatsapp.net`, groups in `@g.us`. Only pass JIDs where a flag explicitly asks for one (e.g. `--chat-id`).
- Auth state: `~/.whatsapp/` (or `~/.whatsapp/{instance}/` for named instances).

## Developing & Testing Changes

The WhatsApp CLI runs as a **daemon** via `screen`. One-shot commands (send, list, etc.) connect to the daemon over a Unix socket. The launcher compiles from source on every invocation (see Rules), but the daemon keeps running the old build until `whatsapp daemon restart`; restart it, then send a message to verify the new behavior.

**If the daemon won't start after a change** (screen session dies immediately), run any foreground command, e.g. `whatsapp --help`: the launcher recompiles and the compile error prints to your terminal. A daemon start also pulls the latest whatsmeow first, so an upstream breaking change surfaces the same way; fix the source against the new API rather than pinning back.

**Testing calls end to end** needs a second WhatsApp account to call and a configured `voice` skill, so it is a manual check, not part of the fast suite: with the daemon running and voice set up, `whatsapp call --to '<other number>'`, answer on the other phone, then `whatsapp say --text 'hello'` and confirm you hear it; speak back and confirm a `call_utterance` notification lands. The deterministic pieces (PCM framing, notification shape, the no-active-call guards) are covered by `go test` in `cli/`.

### Contact Preferences
[How the user prefers to communicate with different contacts]

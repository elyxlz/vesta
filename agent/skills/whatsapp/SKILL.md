---
name: whatsapp
description: WhatsApp messages, contacts, groups (not generic text/message). Requires whatsapp daemon.
---

# WhatsApp - CLI: `whatsapp`

**Setup / first-time auth / re-auth**: see [SETUP.md](SETUP.md).
**Start daemon**: `screen -dmS whatsapp whatsapp serve --notifications-dir ~/agent/notifications`

## Calling the CLI

- Form: `whatsapp <subcommand> [positionals] [--flag value ...]`. **Subcommand goes first**, before any flags.
- Most common subcommands accept leading positional args that the CLI rewrites into flags (e.g. `whatsapp send 'Alice' 'Hi'` is identical to `whatsapp send --to 'Alice' --message 'Hi'`). You can always use the flag form.
- Flags for a specific subcommand: `whatsapp <subcommand> --help`. The top-level `whatsapp` with no args prints the command list.
- Names for `--to` / `--chat-id` / `--group`: contact name, phone (`+E.164`), group name, or JID - the CLI resolves them.

## Reply / Quote
```bash
whatsapp send --to 'Name' --message 'reply text' --reply-to '<message_id>'
```
The `--reply-to` flag quotes the referenced message in WhatsApp's native reply UI. The message ID can be found in incoming notification payloads (`message_id` field) or `list-messages` output.

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

**Chat management**
- `archive-chat` : `<to>`
- `archive-all-chats`
- `delete-chat` : `<to>`
- `clear-all-chats` - destructive; wipes local message DB

**Auth / daemon** (see SETUP.md for details)
- `serve` - starts the background daemon; requires `--notifications-dir`
- `authenticate` - QR-code pairing
- `pair-phone` - phone-number pairing; `--phone <+E.164>`

## Rules

- **Send messages one tool call at a time. Never batch WhatsApp sends in a single parallel tool-call block.**
  *Why:* If one parallel call fails while another succeeds, you can't tell which went through. Retrying "the failed one" sends a duplicate that the recipient sees.

- **`whatsapp serve` requires `--notifications-dir`.**
  *Why:* Without it the daemon exits silently (no stderr), and every subsequent command reports "daemon not running."

- **Do not restart the daemon once the user is authenticated**, unless the user explicitly confirms a full re-auth is acceptable.
  *Why:* Restarting mid-session can invalidate the WhatsApp pairing and force the user to rescan the QR.

- **Never kill whatsapp processes with signals (pkill, killall, kill, os.kill, SIGTERM).** Use `screen -S whatsapp -X quit` only, then sleep briefly, then start a new screen session.
  *Why:* Sending SIGTERM to `whatsapp serve` propagates too broadly and crashes the entire container (exit code 143/144). Screen quit is always sufficient.

- **Before sending to an unknown phone number, save it first with `add-contact`.**
  *Why:* Sending to a raw JID with no saved contact row triggers the `requireManualContact` guard and blocks the send.

- **Right after first-pair auth, `database is locked` can occur transiently during history backfill.**
  *Why:* WhatsApp pushes up to 2 years of history; each conversation is persisted in a short transaction that can briefly exceed the 5s busy-timeout on large chats. If a write fails with "database is locked" within the first minute or two after authentication, wait 10-20 seconds and retry; do not treat it as a real failure. This does not occur on subsequent runs.

## Conventions

- Phone numbers: E.164 with leading `+` (e.g. `+12025551234`).
- JIDs: direct chats end in `@s.whatsapp.net`, groups in `@g.us`. Only pass JIDs where a flag explicitly asks for one (e.g. `--chat-id`).
- Auth state: `~/.whatsapp/` (or `~/.whatsapp/{instance}/` for named instances).

## Developing & Testing Changes

The WhatsApp CLI runs as a **daemon** via `screen`. One-shot commands (send, list, etc.) connect to the daemon over a Unix socket. This means:

1. **Rebuild**: `cd ~/agent/skills/whatsapp/cli && CGO_ENABLED=1 go build -tags "fts5" -o ~/.local/bin/whatsapp .`
2. **Restart daemon**: The running daemon uses the old binary. You MUST restart it to pick up changes:
   ```bash
   screen -S whatsapp -X quit
   sleep 1
   screen -dmS whatsapp whatsapp serve --notifications-dir ~/agent/notifications
   ```
3. **Test**: Send a message and verify the new behavior. The daemon handles all command execution, so changes won't take effect until step 2.

**Common mistake**: rebuilding the binary and testing immediately without restarting the daemon. The CLI client just forwards commands to the daemon over the socket, so the daemon process must be running the new binary.

### Contact Preferences
[How the user prefers to communicate with different contacts]

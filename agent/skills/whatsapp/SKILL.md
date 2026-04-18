---
name: whatsapp
description: Use when the user mentions "whatsapp" or "wa", or asks to send/read/react-to WhatsApp messages, contacts, or groups. Does NOT cover generic "text"/"message" intents — those may mean Telegram or SMS. Requires the `whatsapp serve` daemon.
---

# WhatsApp — CLI: `whatsapp`

**Setup / first-time auth / re-auth**: see [SETUP.md](SETUP.md).
**Start daemon**: `screen -dmS whatsapp whatsapp serve --notifications-dir ~/agent/notifications`

## Quick Reference

Run `whatsapp --help` or `whatsapp <command> --help` for the full flag list.

```bash
whatsapp send --to 'Name' --message 'Hello!'                  # --to: contact name, phone, or group
whatsapp send --to '+12025551234' --message 'Hi'              # phone numbers need leading +
whatsapp send-file --to 'Name' --file-path /path/to/file.pdf
whatsapp react --chat-id '<jid>' --message-id '<id>' --emoji '👍'
whatsapp revoke-message --to 'Name' --message-id '<id>'       # unsend
whatsapp download-media --to 'Name' --message-id '<id>'       # saved to ~/.whatsapp/downloads/
whatsapp chats
whatsapp messages --to 'Name' --limit 20                      # reads local DB only
whatsapp backfill --to 'Name'                                 # asks the phone for older history
whatsapp contacts
whatsapp groups
whatsapp add-contact --name 'Name' --phone '+12025551234'
```

## Rules

- **Send messages one tool call at a time — never batch WhatsApp sends in a single parallel tool-call block.**
  *Why:* If one parallel call fails while another succeeds, you can't tell which went through. Retrying "the failed one" sends a duplicate that the recipient sees.

- **Subcommand goes before flags.** Use `whatsapp serve --instance foo`, not `whatsapp --instance foo serve`.
  *Why:* Global flags parsed before the subcommand are silently misinterpreted by the CLI.

- **`whatsapp serve` requires `--notifications-dir`.**
  *Why:* Without it the daemon exits silently (no stderr), and every subsequent command reports "daemon not running."

- **Do not restart the daemon once the user is authenticated**, unless the user explicitly confirms a full re-auth is acceptable.
  *Why:* Restarting mid-session can invalidate the WhatsApp pairing and force the user to rescan the QR.

- **Before sending to an unknown phone number, save it first with `add-contact`.**
  *Why:* Sending to a raw JID that has no saved contact row triggers the `requireManualContact` guard and blocks replies/notifications from resolving correctly.

## Conventions

- Phone numbers: E.164 with leading `+` (e.g. `+12025551234`).
- JIDs: direct chats end in `@s.whatsapp.net`, groups in `@g.us`. Only pass JIDs where a flag explicitly asks for one (e.g. `--chat-id`).
- Auth state: `~/.whatsapp/` (or `~/.whatsapp/{instance}/` for named instances).

### Contact Preferences
[How the user prefers to communicate with different contacts]

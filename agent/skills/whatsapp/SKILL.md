---
name: whatsapp
description: This skill should be used when the user asks about "whatsapp", "message", "text", "chat", or needs to send/receive messages via WhatsApp. Requires a background daemon.
---

# WhatsApp — CLI: whatsapp

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `screen -dmS whatsapp whatsapp serve --notifications-dir ~/vesta/notifications`

## Gotchas
- CLI syntax: command MUST come before flags. `whatsapp serve --instance name` NOT `whatsapp --instance name serve`
- `send` uses flags, not positional args: `whatsapp send --to 'Name' --message 'text'`
- `--to` accepts contact names, phone numbers, or group names — the CLI resolves them to JIDs
- `--notifications-dir` is REQUIRED for `serve` — it will exit silently without it
- **Never send multiple messages in parallel tool calls.** If one parallel call is rejected/fails while another succeeds, you may mistakenly resend the successful one — causing duplicates. Always send WhatsApp messages sequentially (one tool call at a time)

## Authentication
Pair-phone is the default (and preferred) auth method. It sends a push notification to the phone and is much faster than scanning a QR code.
```bash
whatsapp pair-phone --phone '+1234567890'  # generates a pairing code
```
QR code auth (`whatsapp authenticate`) still works as a fallback but is slower — requires emailing the QR image and scanning before it expires (~60s).

## Quick Reference
```bash
whatsapp send --to '+1234567890' --message 'Hello!'
whatsapp chats
whatsapp contacts
whatsapp messages --to 'Name' --limit 20
whatsapp groups
whatsapp react --chat-id "<jid>" --message-id "<id>" --emoji "👍"
whatsapp backfill --to 'Name'
whatsapp send-file --to "+1234567890" --file-path /path/to/document.pdf
whatsapp revoke-message --to 'Name' --message-id '<id>'  # delete/unsend a message
```

## Notes
- Phone numbers must include country code with `+` prefix
- Chat IDs are JIDs (e.g., `1234567890@s.whatsapp.net`)
- Group IDs end with `@g.us`
- The binary is installed to `~/.local/bin/whatsapp`
- Auth state is stored in `~/.whatsapp/` (default) or `~/.whatsapp/{instance}/` for named instances

### Contact Preferences
[How the user prefers to communicate with different contacts]

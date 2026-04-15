---
name: whatsapp
description: This skill should be used when the user asks about "whatsapp", "message", "text", "chat", or needs to send/receive messages via WhatsApp. Requires a background daemon.
---

# WhatsApp - CLI: whatsapp

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `screen -dmS whatsapp whatsapp serve --notifications-dir ~/notifications`

## Gotchas
- CLI syntax: command MUST come before flags. `whatsapp serve --instance name` NOT `whatsapp --instance name serve`
- `send` uses flags, not positional args: `whatsapp send --to 'Name' --message 'text'`
- `--to` accepts contact names, phone numbers, or group names (the CLI resolves them to JIDs)
- `--notifications-dir` is REQUIRED for `serve`. It will exit silently without it
- **Never send multiple messages in parallel tool calls.** If one parallel call is rejected/fails while another succeeds, you may mistakenly resend the successful one, causing duplicates. Always send WhatsApp messages sequentially (one tool call at a time)

## Authentication
QR code is the default (and preferred) auth method. Run `whatsapp authenticate`, upload the QR image, and have the user scan it from WhatsApp > Linked Devices.
```bash
whatsapp authenticate
```
Phone pairing (`whatsapp pair-phone --phone '+1234567890'`) works as a fallback if QR scanning isn't convenient.

## Quick Reference
Run `whatsapp --help` or `whatsapp <command> --help` for full flags and options not listed here.
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
whatsapp download-media --to 'Name' --message-id '<id>'  # download image/video/doc, saved to ~/.whatsapp/downloads/
```

## Notes
- Phone numbers must include country code with `+` prefix
- Chat IDs are JIDs (e.g., `1234567890@s.whatsapp.net`)
- Group IDs end with `@g.us`
- The binary is installed to `~/.local/bin/whatsapp`
- Auth state is stored in `~/.whatsapp/` (default) or `~/.whatsapp/{instance}/` for named instances

### Contact Preferences
[How the user prefers to communicate with different contacts]

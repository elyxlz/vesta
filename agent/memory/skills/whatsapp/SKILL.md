---
name: whatsapp
description: This skill should be used when the user asks about "whatsapp", "message", "text", "chat", or needs to send/receive messages via WhatsApp. IMPORTANT — this skill requires a background daemon. Before doing anything, immediately make sure the daemon is running. Read this skill to learn how.
---

# WhatsApp — CLI: whatsapp

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `screen -dmS whatsapp whatsapp serve`

## Quick Reference
```bash
whatsapp send '+1234567890' 'Hello!'
whatsapp send '+1234567890' 'Photo' --attachment /path/to/image.jpg
whatsapp chats
whatsapp contacts
whatsapp messages --chat-id "<jid>" --limit 20
whatsapp groups
whatsapp react --chat-id "<jid>" --message-id "<id>" --emoji "👍"
whatsapp backfill --chat-id "<jid>"
whatsapp send-file --to "+1234567890" --file /path/to/document.pdf
```

## Notes
- Phone numbers must include country code with `+` prefix
- Chat IDs are JIDs (e.g., `1234567890@s.whatsapp.net`)
- Group IDs end with `@g.us`
- The binary is installed to `/usr/local/bin/whatsapp`
- Auth state is stored in `~/data/whatsapp/`

### Contact Preferences
[How the user prefers to communicate with different contacts]

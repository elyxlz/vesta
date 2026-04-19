---
name: telegram
description: Use this skill to reply to notifications with `source=telegram`, or when the user asks about "telegram", "tg", "telegram message", or needs to send/receive messages via Telegram. Always reply to telegram notifications via `telegram send`, never via any other channel. Requires a background daemon.
---

# Telegram - CLI: telegram

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `screen -dmS telegram telegram serve --notifications-dir ~/agent/notifications`

## Quick Reference
```bash
telegram send '<contact_name>' 'Hello!'
telegram send '<chat_id>' 'Photo' --attachment /path/to/image.jpg
telegram chats
telegram contacts
telegram messages --to "<contact_name>" --limit 20
telegram groups
telegram react '<contact_name>' '<message_id>' '👍'
telegram send-file --to "<contact_name>" --file-path /path/to/document.pdf
```

## Notes
- Chat IDs are numeric (e.g., `123456789` for private, `-1001234567890` for groups)
- Users must `/start` the bot before it can message them
- Recipients can be resolved by: contact name, @username, or numeric chat ID
- The binary is installed to `/usr/local/bin/telegram`
- Auth state is stored in `~/.telegram/`
- Bot token is stored in `~/.telegram/bot-token`

### Contact Preferences
[How the user prefers to communicate with different contacts]

"""Telegram skill template."""

SKILL_MD = """\
---
name: telegram
description: This skill should be used when the user asks about "Telegram", "telegram message", "telegram chat", or needs to send/receive Telegram messages.
---

# Telegram

## Status: Not yet set up

This skill needs a Telegram integration to be built. Vesta can build one using the Telegram Bot API or a userbot library.

### Options
- **Bot API**: Create a bot via @BotFather, use the HTTP API to send/receive messages
- **Userbot**: Use a library like Telethon or Pyrogram for full account access

### Setup Notes
- Bot token or session credentials will need to be stored securely
- A listener script should place notification JSONs in ~/notifications/ for incoming messages

### Contact Communication Styles
[How to communicate with different contacts]

### Message Preferences
[User's preferred messaging patterns]
"""

SCRIPTS: dict[str, str] = {}

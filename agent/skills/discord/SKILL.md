---
name: discord
description: "Discord: send/receive server messages and DMs; reply to source=discord notifications. Requires daemon."
---

# Discord - CLI: discord

**Setup**: follow [SETUP.md](SETUP.md) (bot token, MESSAGE CONTENT intent, invite url).
**Background**: `screen -dmS discord discord serve --notifications-dir ~/agent/notifications`

## Quick Reference

```bash
discord send 123456789012345678 "message"                # post to a channel id
discord send @987654321098765432 "message"               # DM a user by id
discord send 1234... "reply" --reply 987654321098765432  # reference-reply to a message
discord channels                                         # servers and their text channels
discord history 1234... --limit 20                       # recent messages, oldest first
```

## Replying to notifications

A `source=discord` notification carries `channel_id` and `message_id`.

- DM (no `server` field): `discord send <channel_id> "reply"`.
- Server message: `discord send <channel_id> "reply" --reply <message_id>` so the reply references the message it answers.

## Notes

- Targets are ids: get channel ids from `discord channels` or a notification's `channel_id`, user ids from a notification's `sender_id` (there is no name lookup; ask the user to copy an id from Discord if needed).
- Vesta can only DM users who share a server with the bot.
- DMs and @-mentions interrupt immediately; other server chatter pools until idle, and messages from other bots carry `from_bot=true`. Tune with the notifications skill (fields: `server`, `channel_name`, `sender`, `mention`, `from_bot`).
- Outbound text renders Discord markdown: `**bold**`, `*italic*`, `` `code` ``, plain urls auto-link.
- Token lives at `~/.discord/credentials.json`; re-run `discord authenticate` to rotate it.

### Server Preferences
[Which servers, channels, and people matter, when to use reference replies, tone per server]

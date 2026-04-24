---
name: app-chat
description: Reply to notifications with `source=app-chat` via `app-chat send`. Requires daemon.
---

# App Chat - CLI: app-chat

**Background**: `screen -dmS app-chat app-chat serve --notifications-dir ~/agent/notifications`
**Restart**: Add to `~/agent/prompts/restart.md`:
```
screen -dmS app-chat app-chat serve --notifications-dir ~/agent/notifications
```

## Quick Reference
```bash
app-chat send --message 'Hello!'
app-chat history --search 'query'
app-chat history --limit 20
```

## How it works
- The daemon connects to the agent's `/ws` WebSocket
- When the app user sends a message, the daemon writes a notification file
- You receive the notification and reply with `app-chat send`
- The daemon also relays liveness events (thinking, tool use) to the app

## Notes
- Always reply to app messages using `app-chat send`, not through any other channel
- Send multiple short messages instead of one long one (like texting)
- Lowercase, no bullets, keep messages tight — texting feel, not document feel
- Messages render as markdown: use fenced ``` blocks for code/commands, `[label](url)` for links. Newlines work but multiple short messages still beat one long one
- The daemon auto-reconnects if the agent restarts

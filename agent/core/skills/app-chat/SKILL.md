---
name: app-chat
description: Reply to notifications with `source=app-chat` via `app-chat send`. Requires daemon.
---

# App Chat - CLI: app-chat

## Setup
This is a core skill: its CLI lives under `~/agent/core/skills/app-chat/` (read-only mount), not `~/agent/skills/`.
```bash
uv tool install ~/agent/core/skills/app-chat/cli
```

**Background**: `screen -dmS app-chat app-chat serve`
**Restart**: Add to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:
```
screen -dmS app-chat app-chat serve
```

## Quick Reference
```bash
app-chat send --message 'Hello!'
app-chat history --search 'query'
app-chat history --limit 20
```

## How it works
- When the app user sends a message, the agent receives it and writes the notification itself
- You receive the notification and reply with `app-chat send`
- The daemon holds a `/ws` connection so `app-chat send` can deliver your replies to the app

## Notes
- Always reply to app messages using `app-chat send`, not through any other channel
- Send multiple short messages instead of one long one (like texting)
- Lowercase, no bullets, keep messages tight — texting feel, not document feel
- Messages render as markdown: use fenced ``` blocks for code/commands, `[label](url)` for links. Newlines work but multiple short messages still beat one long one
- The daemon auto-reconnects if the agent restarts

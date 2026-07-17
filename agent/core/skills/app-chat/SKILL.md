---
name: app-chat
description: Reply to notifications with `source=app-chat` via `app-chat send`. Requires daemon.
---

# App Chat - CLI: app-chat

## Setup
This is a core skill: its CLI lives under `~/agent/core/skills/app-chat/` (read-only mount), not `~/agent/skills/`.
```bash
uv tool install --editable ~/agent/core/skills/app-chat/cli
```

**Daemon**: `app-chat daemon start|stop|restart|status`:
- Start is idempotent (a running daemon is a no-op)
- Stop marks the shutdown as intentional so it doesn't fire a `daemon_died` notification
- Status reports the daemon process plus its WS connection state to the agent as JSON

Manage the daemon through these commands, not raw `screen`.
**Restart**: Add to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:
```
app-chat daemon start
```
(The older `screen -dmS app-chat app-chat serve` line still works if a box hasn't picked up the
new subcommand yet.)

## Quick Reference
```bash
app-chat daemon status
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
- `send` enforces short-bubble texting: a wall (over ~220 chars, or any text after a full stop) is rejected so you re-send as several short calls, one thought each. Don't use full stops at all: a `.`, `!` or `?` may only close a bubble, never carry text after it. Ellipses stay free, they're a beat rather than a stop. For genuine reference material the user asked for (a brief, a code block, a list), pass `--longform` to bypass
- Send multiple short messages instead of one long one (like texting)
- Lowercase, no bullets, keep messages tight — texting feel, not document feel
- Messages render as markdown: use fenced ``` blocks for code/commands, `[label](url)` for links. Newlines work
- The daemon auto-reconnects if the agent restarts

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
- Status reports the daemon process state plus its service port and connected client count as JSON

Manage the daemon through these commands, not raw `screen`.
**Restart**: Add to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:
```
running app-chat || { app-chat daemon start; sleep 1; }
```
`app-chat daemon start` registers the `app-chat` service (getting its port) and starts the HTTP
server (intake, history, and the live `/ws` chat socket).

## Quick Reference
```bash
app-chat daemon status
app-chat send --message 'Hello!'
app-chat history --search 'query'
app-chat history --limit 20
```

## How it works
- The daemon is a registered service: it owns the `app-chat` channel, serving `POST /message` (intake) and `GET /history` on its registered port, backed by its own store (`~/.app-chat/app-chat.db`)
- When the app user sends a message, the service persists it and writes the `source=app-chat` notification itself, so a dead process never drops a message the app already showed as delivered
- You receive the notification and reply with `app-chat send`: the reply is persisted to the store, then fanned to any connected `/ws` chat sockets so the app sees it live
- Durability is the store, not the socket: a reply succeeds even with no client connected, and a client refetches history by id on reconnect to pick up anything it missed
- History and search read the same store: `app-chat history` and `app-chat history --search`

## Notes
- Always reply to app messages using `app-chat send`, not through any other channel
- Send multiple short messages instead of one long one (like texting)
- Lowercase, no bullets, keep messages tight — texting feel, not document feel
- Messages render as markdown: use fenced ``` blocks for code/commands, `[label](url)` for links. Newlines work
- The app reconnects its chat socket automatically if the daemon or agent restarts

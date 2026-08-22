---
name: app-chat
description: The user's chat screen in the Vesta app (web, desktop, mobile). Reply to `source=app-chat` notifications via `app-chat send`. Requires daemon.
---

# App Chat - CLI: app-chat

App chat is the built-in chat screen of the Vesta app on web, desktop, and mobile: the user's direct line to you, no third-party account involved. Messages the user types there arrive as `source=app-chat` notifications; replies sent with `app-chat send` appear in their chat live (and as a push notification when they are away). Treat it as a first-class messaging channel with the texting style below.

## Setup
```bash
uv tool install --editable ~/agent/skills/app-chat/cli
```

**Daemon**: `app-chat daemon start|stop|restart|status`:
- Start is idempotent (a running daemon is a no-op) and owns the port registration with vestad
- Stop is the deliberate shutdown, so it doesn't fire the `daemon_died` notification every other exit fires
- Status reports whether the daemon is up and on which port, read from `~/agent/data/daemons/app-chat.pid` and `app-chat.port`

Manage the daemon through these commands, not by launching `app-chat serve` yourself. Startup output lands in `~/agent/logs/app-chat.log`.
**Restart**: So it survives restarts, read the `restart` skill and add this line to your restart daemons:
```
app-chat daemon start
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
- `send` enforces short-bubble texting: a wall (over ~220 chars, or any text after a full stop) is rejected so you re-send as several short calls, one thought each. Don't use full stops at all: a `.`, `!` or `?` may only close a bubble, never carry text after it. Ellipses stay free, they're a beat rather than a stop. For genuine reference material the user asked for (a brief, a code block, a list), pass `--longform` to bypass
- A numbered or bulleted list is fine to send as one message (each item is one short thought); a line-leading marker like `1.` or `2)` is not a full stop, so a list does not need `--longform`
- `send` also enforces VOLUME, which the bubble lint cannot see. After 12 sends in one burst with no reply from the user, further sends are refused. A burst ends when the user writes back, or after 30 minutes of quiet, so a first message after a silence is never blocked. Bypass with `--burst`, for a real emergency only (a deadline, a cancellation, a broken service). `--longform` does NOT bypass it: a run of well-formed bubbles is the failure this catches
- **When the burst lint fires, the answer is almost never `--burst`.** It fires when you are correcting yourself in public. Fix the one bubble that is wrong instead of re-sending the whole thing, and prefer verifying before the first send: an answer that is right the first time is faster than a fast answer plus three retractions
- Send multiple short messages instead of one long one (like texting)
- Lowercase, no bullets, keep messages tight, texting feel, not document feel
- Messages render as markdown: use fenced ``` blocks for code/commands, `[label](url)` for links. Newlines work
- The app reconnects its chat socket automatically if the daemon or agent restarts

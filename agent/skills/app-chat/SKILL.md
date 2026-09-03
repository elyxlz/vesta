---
name: app-chat
description: The user's chat screen in the Vesta app (web, desktop, mobile). Reply to `source=app-chat` notifications via `app-chat send`; send files with `--attach`. Requires daemon.
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

# The one shape to use for any message body. Replace only the middle lines: a blank line starts the next bubble.
app-chat send --message - <<'MSG'
hey, one thought per paragraph

they go out as separate bubbles, paced like texting
MSG

app-chat send --attach ~/out/chart.png --message - <<'MSG'
here it is!
MSG

app-chat send --longform --message - <<'MSG'   # a brief or list they asked for: the whole body is one bubble
<the brief, blank lines and all>
MSG
app-chat history --search 'query'
app-chat history --limit 20
app-chat attachments list
```

Send every message body through `--message -` and a quoted heredoc, as above. The shell expands nothing inside `<<'MSG'`, so apostrophes, quotes, backticks, `$(...)`, `$200` and newlines all pass through untouched. An inline `--message 'text'` breaks on the first apostrophe, so use it only for text you can see has none.

## How it works
- The daemon is a registered service: it owns the `app-chat` channel, serving `POST /message` (intake) and `GET /history` on its registered port, backed by its own store (`~/.app-chat/app-chat.db`)
- When the app user sends a message, the service persists it and writes the `source=app-chat` notification itself, so a dead process never drops a message the app already showed as delivered
- You receive the notification and reply with `app-chat send`: the reply is persisted to the store, then fanned to any connected `/ws` chat sockets so the app sees it live
- Durability is the store, not the socket: a reply succeeds even with no client connected, and a client refetches history by id on reconnect to pick up anything it missed
- History and search read the same store: `app-chat history` and `app-chat history --search`

## Attachments

Files the user sends from the app arrive on the message notification: the `attachments` attribute lists each file's name, type, size, and an absolute path. Open the path directly: `Read` shows images and PDFs, shell tools handle everything else. The files persist under `~/.app-chat/attachments/` (each in an id directory beside a `.meta.json` carrying name, type, and exact byte size), so you can come back to one later.

Send a file with `--attach` (repeat it for several), with or without a message:

```bash
app-chat send --attach ~/out/budget-2026.pdf --message 'here it is!'
app-chat send --attach chart.png
```

The daemon copies the file into its own store, so a temp file can be removed right after sending. The app renders by type: images and videos inline, audio as a player, anything else as a download tile. Limit 512 MB per file. The short-bubble lint applies to the message text only. When the user asks for a real document, a chart, or anything they will keep, attach the file instead of pasting its contents as text.

Manage the disk they use with the CLI, never by deleting files under `~/.app-chat/attachments/` yourself (a raw delete leaves the user a broken bubble; `rm` here leaves a clean "no longer available" tile):

```bash
app-chat attachments list              # largest first, with count and total_bytes
app-chat attachments list --sort date --limit 20
app-chat attachments rm <id> [<id>...] # frees the bytes, keeps the chat history intact
```

## Notes
- Always reply to app messages using `app-chat send`, not through any other channel
- Send a whole reply in one `app-chat send`, one paragraph per bubble in the heredoc (or one `-m` per bubble for text without apostrophes). The CLI sends them in order with a beat between, like texting. It lints every bubble first, so one malformed bubble stops the reply before any of it goes out
- In a live voice conversation the CLI yields the floor for you: it stops sending the moment the user starts talking, drops the rest of the reply, and reports `stopped_for_user`. A fresh `source=app-chat` notification arrives when they finish. Answer their whole thought fresh then
- `send` enforces short-bubble texting: a wall (over ~220 chars, or any text after a full stop) is rejected so you split it into several bubbles, one thought each (a blank line between them). Don't use full stops at all: a `.`, `!` or `?` may only close a bubble, never carry text after it. Ellipses stay free, they're a beat rather than a stop. For genuine reference material the user asked for (a brief, a code block, a list), pass `--longform` to bypass
- A numbered or bulleted list is fine to send as one bubble (each item is one short thought); a line-leading marker like `1.` or `2)` is not a full stop, so a list does not need `--longform`
- Lowercase, no bullets, keep messages tight, texting feel, not document feel
- Messages render as markdown: use fenced ``` blocks for code/commands, `[label](url)` for links. Newlines work
- The app reconnects its chat socket automatically if the daemon or agent restarts

---
name: chat
description: The user's chat screen in the Vesta app (web, desktop, mobile), and the rooms they share with you and the other agents on this gateway. Reply to `source=chat` notifications via `chat send`; send files with `--attach`. Requires daemon.
---

# Chat - CLI: chat

Chat is where you talk with the user and with the other agents on this gateway. The direct room is the Vesta app's chat screen on web, desktop, and mobile: the user's own line to you, no third-party account involved. Every other room is a group: you, one or more other agents, and the user, who reads every room there is. Nothing you write to another agent is private.

Each message reaches you as a `source=chat` notification carrying its `room`, the `room_name` (outside the direct room), the `sender` (`user` or an agent's name), the room's `members`, the `message`, and the `reply_command` that answers in that room. A message from the user interrupts your work; a message from another agent waits for your next idle gap. Replies you send appear in the user's chat live (and as a push notification when they are away). Treat it as a first-class messaging channel with the texting style below.

## Setup
```bash
uv tool install --editable ~/agent/skills/chat/cli
```

**Daemon**: `chat daemon start|stop|restart|status`:
- Start is idempotent (a running daemon is a no-op) and owns the port registration with vestad
- Stop is the deliberate shutdown, so it doesn't fire the `daemon_died` notification every other exit fires
- Status reports whether the daemon is up and on which port, read from `~/agent/data/daemons/chat.pid` and `chat.port`

Manage the daemon through these commands, not by launching `chat serve` yourself. Startup output lands in `~/agent/logs/chat.log`.
**Restart**: So it survives restarts, read the `restart` skill and add this line to your restart daemons:
```
chat daemon start
```
`chat daemon start` registers the `chat` service (getting its port), starts the HTTP server (intake, history, and the live `/ws` chat socket), and opens the room socket that replicates every room you are in.

## Quick Reference
```bash
chat daemon status

# The one shape to use for any message body. Replace only the middle lines: a blank line starts the next bubble.
chat send --message - <<'MSG'
hey, one thought per paragraph

they go out as separate bubbles, paced like texting
MSG

chat send --room dm:apollo:hermes --message - <<'MSG'   # answer where the notification came from
on it, i have the flight times
MSG

chat send --to hermes --message - <<'MSG'   # the room with one other agent, opened on first use
are you free to take thursday's school run?
MSG

chat send --attach ~/out/chart.png --message - <<'MSG'
here it is!
MSG

chat send --longform --message - <<'MSG'   # a brief or list they asked for: the whole body is one bubble
<the brief, blank lines and all>
MSG
chat rooms
chat peers
chat history --search 'query'
chat history --room dm:apollo:hermes --limit 20
chat attachments list
```

Send every message body through `--message -` and a quoted heredoc, as above. The shell expands nothing inside `<<'MSG'`, so apostrophes, quotes, backticks, `$(...)`, `$200` and newlines all pass through untouched. An inline `--message 'text'` breaks on the first apostrophe, so use it only for text you can see has none.

## Rooms

Address one room per send. Copy the `reply_command` off the notification you are answering and it is already addressed. Every `send` below carries its body the way the Quick Reference shows, `--message -` followed by a `<<'MSG'` heredoc:

```bash
chat rooms                                                # the rooms you are in: "<id>  <name or members>"
chat rooms --json                                         # the same list as JSON
chat peers                                                # the other agents on this gateway
chat rooms create --name 'trip planning' --agents hermes,apollo   # open a group
chat send --message -                                     # no room named: the direct room, the user's own line
chat send --room <id> --message -                         # any room, by the id the notification carries
chat send --to <agent> --message -                        # the room with that one agent, opened on first use
chat history --room <id>                                  # the local copy of that room
```

`--to` and `--room` are exclusive. `chat rooms create` puts you and the agents you name in the room, and the user reads it like every other room.

## Etiquette

- The user is in every room. Say to another agent only what you would say in front of the user, because they see it
- In a group, write when a message names you or when you add something the others do not have. Silence is the default: every message you send costs the user attention
- Keep a message to another agent short and concrete: one question, one answer, one fact. Ask for what they alone hold and act on the answer yourself
- When you do write, write in the room the message came from: a peer's question is answered in its own room, never in the user's direct line
- A refused send is finished business, not an error to retry:
  - `user_speaking` means the user started talking. Drop the rest of the reply. A fresh notification arrives when they finish, and you answer their whole thought then
  - The burst guard refuses once a room holds 40 agent messages since the user last spoke. Stop writing in that room; it opens again when the user writes

## How it works
- Your gateway (vestad) holds every room and every message in them: it is the node. The daemon holds one socket to it and mirrors every room you are in into its own store (`~/.chat/chat.db`). On every connect it pulls each room's history by id, so a dropped socket heals itself and no message is lost or doubled
- Every message you did not send becomes one `source=chat` notification. Your own reply comes back on the same socket and is stored with no notification
- `chat send` posts through the node before it answers, so a bubble the command reports as sent is on the node and durable with no client connected
- Attachments arrive downloaded: the notification names a path under `~/.chat/attachments/` that you open directly. A file whose bytes did not arrive is named `could not be fetched from the node` in place of its path, so say that to the sender instead of guessing at the contents
- `chat history` and `chat history --search` read the local copy, one room at a time

## Attachments

Files the user or another agent sends arrive on the message notification: the `attachments` attribute lists each file's name, type, size, and an absolute path. Open the path directly: `Read` shows images and PDFs, shell tools handle everything else. The files persist under `~/.chat/attachments/` (each in an id directory beside a `.meta.json` carrying name, type, and exact byte size), so you can come back to one later.

Send a file with `--attach` (repeat it for several), with or without a message:

```bash
chat send --attach ~/out/budget-2026.pdf --message 'here it is!'
chat send --attach chart.png
chat send --room <id> --attach ~/out/itinerary.pdf
```

The daemon uploads the file and keeps a copy, so a temp file can be removed right after sending. The app renders by type: images and videos inline, audio as a player, anything else as a download tile. Limit 512 MB per file, 10 files on one message. The short-bubble lint applies to the message text only. When the user asks for a real document, a chart, or anything they will keep, attach the file instead of pasting its contents as text.

Manage the disk they use with the CLI, never by deleting files under `~/.chat/attachments/` yourself (a raw delete leaves the user a broken bubble; `rm` here leaves a clean "no longer available" tile):

```bash
chat attachments list              # largest first, with count and total_bytes
chat attachments list --sort date --limit 20
chat attachments rm <id> [<id>...] # frees the bytes, keeps the chat history intact
```

## Notes
- Answer a `source=chat` notification with the `reply_command` it carries, not through any other channel
- Send a whole reply in one `chat send`, one paragraph per bubble in the heredoc (or one `-m` per bubble for text without apostrophes). The CLI sends them in order with a beat between, like texting. It lints every bubble first, so one malformed bubble stops the reply before any of it goes out
- In a live voice conversation the CLI yields the floor for you: it stops sending the moment the user starts talking, drops the rest of the reply, and reports `stopped_for_user`. A fresh `source=chat` notification arrives when they finish. Answer their whole thought fresh then
- `send` enforces short-bubble texting: a wall (over ~220 chars, or any text after a full stop) is rejected so you split it into several bubbles, one thought each (a blank line between them). Don't use full stops at all: a `.`, `!` or `?` may only close a bubble, never carry text after it. Ellipses stay free, they're a beat rather than a stop. For genuine reference material the user asked for (a brief, a code block, a list), pass `--longform` to bypass
- A numbered or bulleted list is fine to send as one bubble (each item is one short thought); a line-leading marker like `1.` or `2)` is not a full stop, so a list does not need `--longform`
- Lowercase, no bullets, keep messages tight, texting feel, not document feel
- Messages render as markdown: use fenced ``` blocks for code/commands, `[label](url)` for links. Newlines work
- The app reconnects its chat socket automatically if the daemon or agent restarts
- `chat import-to-node` hands the node the direct conversation this store holds. A migration step runs it; leave it alone otherwise

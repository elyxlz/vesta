---
name: telegram
description: Telegram: send/receive messages; reply to source=telegram notifications. Requires daemon.
---

# Telegram - CLI: telegram

**Setup**: See [SETUP.md](SETUP.md)
**Daemon**: `telegram daemon start|stop|restart|status`. Start is idempotent; stop/restart quit the watchdog first so it cannot race a manual restart into two daemons. Manage the daemon only through these commands, never raw `screen`.

## Quick Reference
```bash
telegram send '<contact_name>' 'Hello!'
telegram send '<contact_name>' 'long text' --message-file /tmp/body.txt   # prefer --message-file when the body has apostrophes, quotes, backticks, $(...), or multiple lines: an inline string lets the shell mangle or even evaluate it
telegram send '<contact_name>' 'reply' --reply-to '<message_id>'          # quote a message
telegram send '<contact_name>' '<a brief or list they asked for>' --longform  # bypass short-bubble lint
telegram chats
telegram contacts
telegram messages --to "<contact_name>" --limit 20
telegram groups
telegram react '<contact_name>' '<message_id>' '👍'
telegram send-file --to "<contact_name>" --file-path /path/to/document.pdf
telegram send-voice --to "<contact_name>" --file-path /path/to/note.ogg
```

## Edited messages

People change their minds after they hit send, so a message you already read can change. An edit arrives as an `edit` notification whose body carries what the message says now, just like a plain message, naming the message that changed (`target_message_id`) and the text you last saw (`old_text`). The stored message is rewritten, so `list-messages` and search show only the new text. Answer again only if the edit asks something new: a fixed typo needs nothing from you. Deletions are invisible here, Telegram never tells a bot that a message was deleted.

## Interactive UI (inline buttons + callbacks)

Send tappable buttons, get notified when the owner taps, then answer the tap and/or edit the
message in place. This is the full "dynamic UI" loop: menus, confirm/deny prompts, live-updating
status messages.

```bash
# 1. Send a message with an inline keyboard.
#    --buttons format: rows separated by ';', buttons within a row by ',',
#    each button is "Label=callback_data" (or "Label=url:https://..." for a link button).
telegram send 'Elio' 'Approve the draft?' --buttons 'yes=approve,no=reject;edit first=edit'

# 2. The owner taps a button → a notification arrives:
#    {"source":"telegram","type":"callback_query","data":"approve",
#     "callback_id":"...","chat_id":...,"message_id":...}

# 3. Answer the tap (stops the button's loading spinner; --text shows a toast, --alert a popup).
telegram answer-callback '<callback_id>' --text 'approved ✓'

# 4. Optionally edit the message in place to reflect the choice (and drop/replace the buttons).
telegram edit-message 'Elio' '<message_id>' 'Approved ✓' [--buttons '...']
```

## Other commands
```bash
telegram delete-message '<to>' '<message_id>'                              # unsend
telegram send-chat-action '<to>' typing                                   # transient "typing…" status
telegram pin-message '<to>' '<message_id>' [--silent]
telegram unpin-message '<to>' ['<message_id>']                            # omit id to unpin latest
```

Notification types written for the agent: `message`, `callback_query` (button tap), `reaction`
(inbound reactions are not decoded by the v5 library, so they don't currently fire; sending
reactions via `react` works). Aliases: `send`/`edit`/`del`/`voice`/`action`/`pin`/`unpin`.

## Notes
- `send-message` enforces short-bubble texting: a wall (over ~220 chars, or any text after a full stop) is rejected so you re-send as several short calls, one thought each. Don't use full stops at all: a `.`, `!` or `?` may only close a bubble, never carry text after it. Ellipses stay free, they're a beat rather than a stop. For genuine reference material the user asked for (a brief, a code block, a list), pass `--longform` to bypass. `--message-file` sends are linted too, so `--longform` is the only escape hatch.
- A numbered or bulleted list is fine to send as one message (each item is one short thought); a line-leading marker like `1.` or `2)` is not a full stop, so a list does not need `--longform`.
- Chat IDs are numeric (e.g., `123456789` for private, `-1001234567890` for groups)
- Users must `/start` the bot before it can message them
- Recipients can be resolved by: contact name, @username, or numeric chat ID
- The binary is installed to `/usr/local/bin/telegram`
- Auth state is stored in `~/.telegram/`
- Bot token is stored in `~/.telegram/bot-token`

### Contact Preferences
[How the user prefers to communicate with different contacts]

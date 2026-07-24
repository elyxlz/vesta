---
name: slack
description: "Slack: send/receive workspace messages, DMs, threads; reply to source=slack notifications. Requires daemon."
---

# Slack - CLI: slack

**Setup**: follow [SETUP.md](SETUP.md) (Slack app from a manifest, then two tokens).
**Background**: `screen -dmS slack slack serve --notifications-dir ~/agent/notifications`

## Quick Reference

```bash
slack send "#general" "message"                            # post to a channel
slack send "@elio" "message"                               # DM a user by name
slack send D0123ABCD "message"                             # send to a raw conversation id
slack send C0123ABCD "reply" --thread 1751970000.000100    # reply in a thread
slack channels                                             # channels + whether Vesta is a member
slack users                                                # workspace members (id, display name, @handle)
slack history "#general" --limit 20                        # recent messages, oldest first
slack history C0123ABCD --thread 1751970000.000100         # read one thread
```

## Replying to notifications

A `source=slack` notification carries `channel_id`, `message_ts`, and `thread_ts` when the message is already in a thread.

- DM (`channel_id` starts with `D`): `slack send <channel_id> "reply"`.
- Channel message: prefer replying in the thread, `slack send <channel_id> "reply" --thread <message_ts>` (use the notification's `thread_ts` when present so the reply stays in the existing thread).

## Notes

- Targets: `#name`, `@user` (matched against handle, display name, real name), or a raw id (`C...` channel, `D...` DM, `U...` user, which auto-opens the DM).
- Vesta must be invited to a channel to read or post there: the user runs `/invite @Vesta` in that channel. DMs need no invite.
- DMs, group DMs, and @-mentions interrupt immediately; ambient channel chatter pools until idle. Tune with the notifications skill (fields: `channel_name`, `sender`, `mention`).
- Outbound text renders Slack mrkdwn: `*bold*`, `_italic_`, `` `code` ``, `<https://url|label>`.
- Tokens live at `~/.slack/credentials.json`; re-run `slack authenticate` to rotate them.

### Channel Preferences
[Which channels and people matter, when to reply in thread vs. top level, tone per channel]

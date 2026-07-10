# Microsoft Teams (CLI: microsoft teams)

**Teams is set up by `microsoft auth setup --account <email>`** along with mail and calendar; you do
not authorize it separately (see [SETUP.md](../SETUP.md)). On a locked tenant the one browser sign-in
covers Teams too, and the daemon keeps its token fresh.

Every command takes `--backend {auto,graph,owa-rest}` (default `auto`): `graph` uses the device-flow
token, `owa-rest` uses the browser-captured token, `auto` tries Graph then falls back. If a command
returns a scope error, the token was captured without that permission, re-run `auth setup --browser`.

The lower-level `auth teams-login` / `teams-complete` / `teams-capture` still exist for manual
control, but `auth setup` is the path.

## Chats

```bash
microsoft teams chats --account you@company.com                          # recent chats, newest message first
microsoft teams messages --account you@company.com --chat <chat_id>       # messages in a chat
microsoft teams send --account you@company.com --chat <chat_id> --body "on my way"
microsoft teams start --account you@company.com --with bob@company.com --body "hi"      # new 1:1
microsoft teams start --account you@company.com --with a@co.com b@co.com --topic "Launch" --body "kickoff"  # group
```

`chats` and `messages` print `id` in the last column (needed for `--chat`). `start` makes a one-on-one
when `--with` names one person, a group (with an optional `--topic`) for two or more.

## Teams and channels

```bash
microsoft teams teams --account you@company.com                          # joined teams (with ids)
microsoft teams channels --account you@company.com --team <team_id>
microsoft teams post --account you@company.com --team <team_id> --channel <channel_id> --body "ship it"
microsoft teams reply --account you@company.com --team <team_id> --channel <channel_id> --message <msg_id> --body "agreed"
microsoft teams channel-messages --account you@company.com --team <team_id> --channel <channel_id>
```

Posting and replying to channels work out of the box. **Reading** channel messages
(`channel-messages`) needs the admin-only `ChannelMessage.Read.All` scope, so it fails on the default
client unless a tenant admin has granted it (or you use your own app registration); chats need no
admin consent.

## Presence

```bash
microsoft teams presence --account you@company.com                       # your availability + activity
microsoft teams set-presence --account you@company.com --availability Busy --expires PT1H
microsoft teams clear-presence --account you@company.com
```

`--availability`: Available / Busy / DoNotDisturb / BeRightBack / Away / Offline. `--expires` is an
ISO 8601 duration (e.g. `PT1H`, `PT30M`); omit it for Graph's own default. Preferred presence only
shows while you have a live Teams session signed in.

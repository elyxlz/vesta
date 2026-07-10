# Microsoft Teams (CLI: microsoft teams)

Teams runs over the same Graph transport as mail, with its **own** sign-in so a mail-only account is
never prompted for Teams scopes. Pick the path by account type (ask the user first, same rule as the
mail sign-in): a **personal** account uses device-code, a **work/school** account on a locked tenant
uses the browser capture below.

```bash
microsoft auth teams-login                       # personal accounts: device-code sign-in; returns a URL + code
microsoft auth teams-complete --flow-cache <cache>  # finish after signing in
```

If `teams-complete` returns `admin_consent_required`, the tenant is locked (a work/school account),
switch to the browser capture. Capture a token from Teams on the web (same browser-capture path as
email's `owa-login`, agent-driven and non-blocking):

```bash
microsoft auth teams-capture --account you@company.com   # captures, or returns sign_in_required
```

If the browser is not signed in, drive the sign-in with the `browser` skill, then run it again. When
the agent cannot reach the browser, let the user run `auth_commands.TEAMS_TOKEN_SNIPPET` in their own
Teams DevTools console and paste the token: `microsoft auth teams-capture --account you@company.com --token <TOKEN>`.

Every command takes `--backend {auto,graph,owa-rest}` (default `auto`): `graph` uses the device-flow
token, `owa-rest` uses the browser-captured token, `auto` tries Graph then falls back.

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

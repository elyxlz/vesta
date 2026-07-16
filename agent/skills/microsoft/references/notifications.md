# Notifications (CLI: microsoft notify)

The `serve` daemon watches each account's inbox by default and writes one notification per new email (source `microsoft`, type `email`, with a `folder` field). To watch more folders (e.g. a folder an inbox rule routes newsletters into), set the per-account watch list; the daemon re-reads it every cycle, no restart:

```bash
microsoft notify list --account user@example.com                      # show watched folders
microsoft notify add --account user@example.com --folder Newsletters  # also notify on this folder
microsoft notify add --account user@example.com --all                 # watch every folder (prune noisy ones after)
microsoft notify remove --account user@example.com --folder inbox     # stop notifying on inbox
```

`notify add --folder` validates the folder exists first. Removing every folder mutes the account. The watch list lives in `~/.microsoft/notify.json`. Watching is time-based: it fires on **new arrivals** (including rule-routed mail), not on messages you manually move into a folder.

Once an account has authorized Teams (via `auth setup`), the daemon also watches its Teams chats and writes one notification per incoming chat message (source `microsoft`, type `teams`, with `sender`, `topic`, `chat_id`; your own outgoing messages are skipped). Teams chat notifications interrupt by default, like a direct message. Reply with `microsoft teams send --chat <chat_id>`.

Where the account also has Teams **channel** access, the daemon additionally watches channel messages and writes one notification per new channel post (type `teams`, with `sender`, `topic` = `Team / Channel`, `team_id`, `channel_id`; your own posts are skipped). Unlike chats, channel notifications are **non-interrupting**, channels are broadcast, so they snooze until you're idle rather than interrupting on every post. Reply with `microsoft teams reply --channel <channel_id> --team <team_id> ...`. Channel watching degrades gracefully: reading channel messages needs the admin-granted `ChannelMessage.Read.All` Graph permission, which many accounts (e.g. browser-capture / OWA-REST-only) lack. When an account can't read channels the daemon silently keeps working with **chats only**, no errors, no missing-permission spam.

The daemon silently refreshes browser-captured tokens before they expire. If a sign-in finally lapses (the SSO session ended), it emits a `type=auth_needed` notification (with `account` and a `message`); re-run `microsoft auth setup --account <email> --browser` to sign in again.

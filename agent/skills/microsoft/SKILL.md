---
name: microsoft
description: Outlook/Microsoft 365 work account via Graph: read/send/reply/forward email, drafts, flag/categorize, move/archive, folders, attachments, block senders, calendar and meetings, and new-mail paging. Requires daemon.
---

# Microsoft - CLI: microsoft

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `screen -dmS microsoft microsoft serve --notifications-dir ~/agent/notifications`

## Two backends (Graph + OWA REST)

Every email, folder, and calendar command runs over one of two paths, chosen with
`--backend {auto,graph,owa-rest}` (default `auto`):

- **`graph`**: the official Microsoft Graph API (`graph.microsoft.com`). The
  clean, supported, first-class path. Uses a device-flow OAuth token (see SETUP).
- **`owa-rest`**: calls the OWA REST API (`outlook.office.com/api/v2.0`) with a
  token captured from a signed-in Outlook-on-the-web session in the agent's own
  browser (`microsoft auth owa-login`). This is the universal fallback: locked
  tenants that block Graph usually block device-code flow too, and browser capture
  works on all of them. The capture is agent-driven and runs on the agent's box, so
  it needs nothing from the user's machine.
- **`auto`** (default): tries Graph; on a permission failure (401/402/403, or the
  account is only authorized for OWA REST) falls back to OWA REST. Non-permission
  errors propagate unchanged so the fallback never hides real bugs.

Both backends support the full command surface below. The one exception:
inbox rules (`block`/`unblock`) are Graph-only, since OWA REST v2.0 does not
expose them; on the REST path they raise a clear error pointing to `--backend graph`.

**OWA REST setup** (only needed if Graph is blocked on the tenant). Open Outlook
on the web in the agent's browser and sign in with the `browser` skill (navigate,
enter the user's credentials, handle MFA), then capture the token:
```bash
microsoft auth owa-login --account you@company.com
```
If the session is not signed in yet it returns `sign_in_required` (no blocking);
finish the sign-in via the `browser` skill and run it again. The captured token
lasts about 24 h; re-run to refresh. `auto` uses it automatically once captured.

When the agent cannot reach the user's browser (agent on another machine), let the
user sign in on their **own** browser and paste just the token, so their password and
MFA never reach the agent. Give them the one-line snippet `auth_commands.OWA_TOKEN_SNIPPET`
to run in the Outlook DevTools console (it copies the token to their clipboard), then:
```bash
microsoft auth owa-login --account you@company.com --token <PASTED_TOKEN>
```
On a tenant that still permits device flow, `owa-login --device` (then
`owa-complete`) does a code sign-in instead, which MSAL auto-refreshes.

## Email

```bash
microsoft email list --account user@example.com
microsoft email get --account user@example.com --id <email_id>
microsoft email send --account user@example.com --to bob@example.com --subject "Hello" --body "Message"
microsoft email reply --account user@example.com --id <email_id> --body "Thanks!"
microsoft email reply --account user@example.com --id <email_id> --body "Thanks all!" --reply-all
microsoft email forward --account user@example.com --id <email_id> --to bob@example.com --body "fyi, see below"
microsoft email search --account user@example.com --query "project update"
microsoft email list --account user@example.com --search "project update"   # alias for the line above
```

Both `email search --query "..."` and `email list --search "..."` run the same search (search defaults to all folders; add `--folder` to narrow). Before making any negative claim ("not in the inbox") off empty output, confirm the command actually exited 0: an empty result with a non-zero exit means the query failed, not that nothing matched.

`send`, `reply`, and `forward` accept `--attachments file1 file2` and `--html` (treats `--body` as HTML). `forward` requires `--to` and also takes `--cc`.

## Organize messages

```bash
microsoft email update --account user@example.com --id <email_id> --is-read true      # mark read/unread
microsoft email update --account user@example.com --id <email_id> --flagged            # flag for follow-up
microsoft email update --account user@example.com --id <email_id> --unflagged          # clear the flag
microsoft email update --account user@example.com --id <email_id> --categories Tax Receipts
microsoft email move --account user@example.com --id <email_id> --to-folder Archive     # any folder (well-known key or display name)
microsoft email archive --account user@example.com --id <email_id>                      # shortcut for move to Archive
```

`--to-folder` accepts a well-known key (`inbox`, `sent`, `drafts`, `deleted`, `junk`, `archive`) or a folder's display name (resolved to its id automatically).

## Drafts

```bash
microsoft email draft --account user@example.com --to bob@example.com --subject "Proposal" --body "rough notes..."
microsoft email draft --account user@example.com --reply-to <email_id> --body "draft answer for review"    # threaded reply draft
microsoft email draft --account user@example.com --forward <email_id> --to bob@example.com --body "fyi"      # forward draft
```

`draft` saves to the Drafts folder without sending. `--reply-to` / `--forward` (mutually exclusive) build a **threaded** draft off an existing message; `--subject` is optional then (inherited). Accepts `--cc`/`--bcc`/`--attachments`.

## Folders

```bash
microsoft folder list --account user@example.com                                  # every folder + unread/total counts
microsoft folder status --account user@example.com --folder inbox                 # counts for one folder
microsoft folder create --account user@example.com --name "Newsletters"           # nest with --parent <folder_id>
microsoft folder rename --account user@example.com --id <folder_id> --name "News"
microsoft folder delete --account user@example.com --id <folder_id>
```

`folder list` also prints each folder's `id` (needed for `--parent`, `rename`, `delete`).

## Email Block/Unblock

Block or unblock senders to filter unwanted emails:

```bash
microsoft email block --account user@example.com --sender spam@example.com
microsoft email unblock --account user@example.com --sender spam@example.com
microsoft email block --account user@example.com --list  # show blocked senders
```

After blocking a phishing/spam sender, clean up messages that already arrived:

```bash
microsoft email delete --account user@example.com --id <email_id>            # delete one message
microsoft email delete --account user@example.com --sender spam@example.com  # delete all from a sender
microsoft email delete --account user@example.com --sender spam@example.com --permanent  # hard delete
```

Delete soft-deletes to Deleted Items by default (moves to `deleteditems`); `--permanent` hard-deletes. `--id` and `--sender` are mutually exclusive and exactly one is required.

If block returns 403, re-authorize:
```bash
microsoft auth add --account user@example.com
```

## Calendar

```bash
microsoft calendar list --account user@example.com --days-ahead 7
microsoft calendar create --account user@example.com --subject "Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/London"
microsoft calendar respond --account user@example.com --id <event_id> --response accept
```

## Notes
- `--account` required for all email/calendar commands (find with: `microsoft auth list`)
- `--timezone` required for calendar create/update (IANA names like "Europe/London")
- `--response` choices: accept / decline / tentativelyAccept
- `--to`/`--cc`/`--attendees` accept multiple space-separated values
- `--no-cancellation` on delete skips notifying attendees
- `--no-details` on calendar list returns compact output (no body/attendees)
- `--user-timezone` on calendar list converts times to the given IANA timezone
- `--folder` on email list/search filters by folder (default "inbox")
- `--no-attachments` on email get skips attachment metadata
- `--save-to` on email get overrides the auto-save path for the body
- **`email get` always saves the body to disk** under `~/.microsoft/emails/<timestamp>_<subject>_<id>.txt` and strips it from the JSON response. The JSON returns `body: {saved_to, length, size_bytes, _note}` plus the legacy `body_saved_to`, `body_saved_size`, `body_length` fields, and a short `preview`. To inspect content, read the file at `body.saved_to`. The full `body.content` field is intentionally never returned inline to keep agent context small. Bodies over 5000 chars also surface a warning telling you to grep/crop before pasting snippets
- `--categories` on email update accepts multiple space-separated category names; `--flagged`/`--unflagged` set or clear the follow-up flag
- `email list`, `email search`, `calendar list`, `calendar calendars`, and `folder list` default to a compact tab-separated table; pass `--json` for one-line JSON or `--json-pretty` for indented JSON. Graph `@odata.*` metadata is stripped from every result.
- `microsoft auth list` shows registered accounts; `microsoft auth remove --account user@example.com` signs one out

## Email Attachments

```bash
microsoft email attachment --account user@example.com --email-id '<email_id>' --list                                   # list attachment metadata
microsoft email attachment --account user@example.com --email-id '<email_id>' --all                                     # download all (to ~/.microsoft/attachments/<id>)
microsoft email attachment --account user@example.com --email-id '<email_id>' --all --out-dir /tmp/x                     # download all to a dir
microsoft email attachment --account user@example.com --email-id '<email_id>' --attachment-id '<attachment_id>' --save-path /tmp/file.pdf  # one
```

## Notifications

The `serve` daemon watches each account's inbox by default and writes one notification per new email (source `microsoft`, type `email`, with a `folder` field). To watch more folders (e.g. a folder an inbox rule routes newsletters into), set the per-account watch list; the daemon re-reads it every cycle, no restart:

```bash
microsoft notify list --account user@example.com                      # show watched folders
microsoft notify add --account user@example.com --folder Newsletters  # also notify on this folder
microsoft notify add --account user@example.com --all                 # watch every folder (prune noisy ones after)
microsoft notify remove --account user@example.com --folder inbox     # stop notifying on inbox
```

`notify add --folder` validates the folder exists first. Removing every folder mutes the account. The watch list lives in `~/.microsoft/notify.json`. Watching is time-based: it fires on **new arrivals** (including rule-routed mail), not on messages you manually move into a folder.

### Contact Communication Styles
[How to communicate with different contacts. Fill in after data gathering: who are the key contacts, what tone/formality for each, language preferences]

### Email Preferences
[User's email patterns. Fill in after data gathering: greeting style, sign-offs, capitalization, punctuation habits, typical length, tone, which account for what]

### Scheduling Preferences
[User's scheduling patterns. Fill in after data gathering: preferred meeting times, timezone, how they reschedule, buffer preferences]

### Regular Events
[Recurring meetings and commitments. Fill in after data gathering: weekly/monthly recurring events, who with]

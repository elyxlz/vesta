# Email (CLI: microsoft email / folder)

Mailbox commands take `--account <email>` and `--backend {auto,graph,owa-rest}` (see [SETUP.md](../SETUP.md)). Delayed-send management is client-wide as described below.

## Read and send

```bash
microsoft email list --account user@example.com
microsoft email get --account user@example.com --id <email_id>
microsoft email send --account user@example.com --to bob@example.com --subject "Hello" --body "Message"
microsoft email reply --account user@example.com --id <email_id> --body "Thanks!"
microsoft email reply --account user@example.com --id <email_id> --body "Thanks all!" --reply-all
microsoft email forward --account user@example.com --id <email_id> --to bob@example.com --body "fyi, see below"
microsoft email search --account user@example.com --query "project update"
microsoft email list --account user@example.com --since 2021-01-01 --until 2021-12-31   # reach mail by date
microsoft email search --account user@example.com --query "invoice" --since 2021-06-01  # text within a date range
```

`send`, `reply`, and `forward` accept `--attachments file1 file2` and `--html` (treats `--body` as HTML). `forward` requires `--to` and also takes `--cc`.

## Delayed send and undo

Send, reply, and forward operations wait 30 seconds by default across all Microsoft accounts and both email backends. The delay is one persisted setting for the Microsoft client and cannot be overridden on an individual send:

```bash
microsoft email send-delay
microsoft email send-delay --seconds 60
microsoft email pending
microsoft email pending --account user@example.com
microsoft email undo --id <pending_id>
```

Each send, reply, or forward command creates a provider draft and returns a `pending` status with its id and scheduled send time. `microsoft serve` sends due drafts through the backend that created them, and every email command already requires it to be running. Use `undo` to cancel a pending send and delete its provider draft: it works right up until the daemon starts dispatching that message. Set `--seconds 0` for immediate delivery. Explicit drafts are never queued.

`pending` also lists messages whose status is `failed`, with `last_error` saying why: delivery kept erroring, or it was cut off mid-dispatch. A message cut off mid-dispatch may already have been sent, so read the Sent folder before you `undo` it or send it again.

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

## Block / unblock and cleanup

```bash
microsoft email block --account user@example.com --sender spam@example.com
microsoft email unblock --account user@example.com --sender spam@example.com
microsoft email block --account user@example.com --list  # show blocked senders
```

`block`/`unblock` (inbox rules) are **Graph-only**; on `--backend owa-rest` they raise a clear error pointing to `--backend graph`.

After blocking a phishing/spam sender, clean up messages that already arrived:

```bash
microsoft email delete --account user@example.com --id <email_id>            # delete one message
microsoft email delete --account user@example.com --sender spam@example.com  # delete all from a sender
microsoft email delete --account user@example.com --sender spam@example.com --permanent  # hard delete
```

Delete soft-deletes to Deleted Items by default (moves to `deleteditems`); `--permanent` hard-deletes. `--id` and `--sender` are mutually exclusive and exactly one is required.

## Attachments

```bash
microsoft email attachment --account user@example.com --id '<email_id>' --list                                   # list attachment metadata
microsoft email attachment --account user@example.com --id '<email_id>' --all                                     # download all (to ~/.microsoft/attachments/<id>)
microsoft email attachment --account user@example.com --id '<email_id>' --all --out-dir /tmp/x                     # download all to a dir
microsoft email attachment --account user@example.com --id '<email_id>' --attachment-id '<attachment_id>' --save-path /tmp/file.pdf  # one
```

## Notes

- **Message id: `--id` and `--email-id` are interchangeable** on every subcommand that takes one (`get`, `attachment`, `move`, `archive`, `update`, `delete`, `reply`, `reply-draft`, `forward`). Either spelling parses everywhere, so a wrong guess cannot exit 2 with a usage error that reads like an empty result when stderr is suppressed.
- `--folder` on `email list`/`search` filters by folder (default "inbox"). It resolves a display name to the folder id the same way `--to-folder` does on `move`, so a user-created folder such as `Screened` works by name.
- `--since YYYY-MM-DD` / `--until YYYY-MM-DD` on `email list`/`search` (both inclusive) reach mail by date. Plain `search` uses Graph `$search`, which ranks by relevance and buries old mail, so searching a large mailbox for old messages returns nothing useful, and which does not cover Junk Email or Deleted Items, so an empty search is not proof a message never arrived (list those folders: `email list --folder junk` / `--folder deleted`); the date flags switch to a `$filter=receivedDateTime` range ordered newest-first, which reaches any date directly. Graph forbids combining `$search` with `$filter`, so when a `--query` and a date range are given together, the date range is applied server-side and the query is matched client-side (case-insensitive) against subject, sender, and body preview.
- `--no-attachments` on `email get` skips attachment metadata; `--save-to` overrides the auto-save path for the body.
- **`email get` always saves the body to disk** under `~/.microsoft/emails/<account>/<timestamp>_<subject>_<id>.txt` (`<account>` is the `--account` address lowercased, every character that is not a letter or digit replaced by `_`) and strips it from the JSON response. The JSON returns `body: {saved_to, length, size_bytes, _note}` plus the legacy `body_saved_to`, `body_saved_size`, `body_length` fields, and a short `preview`. To inspect content, read the file at `body.saved_to`. The full `body.content` field is intentionally never returned inline to keep agent context small. Bodies over 5000 chars also surface a warning telling you to grep/crop before pasting snippets. `microsoft auth remove --account <email>` deletes that account's saved bodies together with its sign-in.
- `--categories` on `email update` accepts multiple space-separated names; `--flagged`/`--unflagged` set or clear the follow-up flag.

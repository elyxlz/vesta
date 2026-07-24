# Email (CLI: microsoft email / folder)

Every command takes `--account <email>` and `--backend {auto,graph,owa-rest}` (see [SETUP.md](../SETUP.md)).

## Read and send

```bash
microsoft email list --account user@example.com
microsoft email get --account user@example.com --id <email_id>
microsoft email send --account user@example.com --to bob@example.com --subject "Hello" --body "Message"
microsoft email reply --account user@example.com --id <email_id> --body "Thanks!"
microsoft email reply --account user@example.com --id <email_id> --body "Thanks all!" --reply-all
microsoft email forward --account user@example.com --id <email_id> --to bob@example.com --body "fyi, see below"
microsoft email search --account user@example.com --query "project update"
```

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
microsoft email attachment --account user@example.com --email-id '<email_id>' --list                                   # list attachment metadata
microsoft email attachment --account user@example.com --email-id '<email_id>' --all                                     # download all (to ~/.microsoft/attachments/<id>)
microsoft email attachment --account user@example.com --email-id '<email_id>' --all --out-dir /tmp/x                     # download all to a dir
microsoft email attachment --account user@example.com --email-id '<email_id>' --attachment-id '<attachment_id>' --save-path /tmp/file.pdf  # one
```

## Notes

- `--folder` on `email list`/`search` filters by folder (default "inbox").
- `--no-attachments` on `email get` skips attachment metadata; `--save-to` overrides the auto-save path for the body.
- **`email get` always saves the body to disk** under `~/.microsoft/emails/<timestamp>_<subject>_<id>.txt` and strips it from the JSON response. The JSON returns `body: {saved_to, length, size_bytes, _note}` plus the legacy `body_saved_to`, `body_saved_size`, `body_length` fields, and a short `preview`. To inspect content, read the file at `body.saved_to`. The full `body.content` field is intentionally never returned inline to keep agent context small. Bodies over 5000 chars also surface a warning telling you to grep/crop before pasting snippets.
- `--categories` on `email update` accepts multiple space-separated names; `--flagged`/`--unflagged` set or clear the follow-up flag.

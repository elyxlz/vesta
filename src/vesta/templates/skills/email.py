"""Email skill template."""

SKILL_MD = """\
---
name: email
description: This skill should be used when the user asks about "email", "emails", "inbox", "messages", or needs to read/send emails, reply to messages, or manage email communications.
---

# Email — CLI: microsoft

## Quick Reference
```bash
microsoft list-emails --account user@example.com
microsoft get-email --account user@example.com --id <email_id>
microsoft send-email --account user@example.com --to bob@example.com --subject "Hello" --body "Message"
microsoft reply-to-email --account user@example.com --id <email_id> --body "Thanks!"
microsoft search-emails --account user@example.com --query "project update"
```

## Other Commands
```bash
microsoft send-email --account user@example.com --to bob@example.com --cc alice@example.com --subject "Report" --body "See attached" --attachments /path/to/file.pdf
microsoft reply-to-email --account user@example.com --id <email_id> --body "Noted" --reply-all
microsoft create-draft --account user@example.com --to bob@example.com --subject "Draft" --body "WIP"
microsoft get-attachment --account user@example.com --email-id <email_id> --attachment-id <att_id> --save-path /tmp/file.pdf
microsoft update-email --account user@example.com --id <email_id> --is-read true
```

## Notes
- `--account` required for all commands (find with: `microsoft list-accounts`)
- `--to`/`--cc`/`--attendees` accept multiple space-separated values

## Setup: `uv tool install {install_root}/clis/microsoft`
## Background: `microsoft serve &`

### Contact Communication Styles
[How to communicate with different contacts]

### Email Preferences
[User's preferred email handling patterns]
"""

SCRIPTS: dict[str, str] = {}

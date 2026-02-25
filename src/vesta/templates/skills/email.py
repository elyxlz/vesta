"""Email skill template."""

SKILL_MD = """\
---
name: email
description: This skill should be used when the user asks about "email", "emails", "inbox", "messages", or needs to read/send emails, reply to messages, or manage email communications.
---

# Email

You have access to email tools via the `microsoft` CLI. Use them to help the user manage their email communications.

## Setup

Requires two env vars set in the container:
- `MICROSOFT_MCP_CLIENT_ID` — Azure app client ID
- `MICROSOFT_MCP_TENANT_ID` — Azure tenant ID (defaults to `common`)

Install the CLI tool (if not already installed):
```bash
uv tool install {install_root}/clis/microsoft
```

## Commands

```bash
# List emails
microsoft list-emails --account user@example.com --folder inbox --limit 10

# Read a specific email (body saved to file)
microsoft get-email --account user@example.com --id <email_id>

# Send an email
microsoft send-email --account user@example.com --to bob@example.com --subject "Hello" --body "Message"

# Send with CC and attachments
microsoft send-email --account user@example.com --to bob@example.com --cc alice@example.com --subject "Report" --body "See attached" --attachments /path/to/file.pdf

# Create a draft
microsoft create-draft --account user@example.com --to bob@example.com --subject "Draft" --body "WIP"

# Reply to an email
microsoft reply-to-email --account user@example.com --id <email_id> --body "Thanks!"

# Reply all
microsoft reply-to-email --account user@example.com --id <email_id> --body "Thanks!" --reply-all

# Search emails
microsoft search-emails --account user@example.com --query "project update" --limit 10

# Download attachment
microsoft get-attachment --account user@example.com --email-id <email_id> --attachment-id <att_id> --save-path /tmp/file.pdf

# Mark as read/unread
microsoft update-email --account user@example.com --id <email_id> --is-read true

# List authenticated accounts
microsoft list-accounts
```

## Background Monitoring

Start the monitor to get notifications for new emails:
```bash
microsoft serve &
```

## Best Practices

- Always confirm before sending emails
- Summarize long email threads concisely
- Draft professional responses matching the user's tone
- Check for attachments when mentioned in context

### Contact Communication Styles
[How to communicate with different contacts]

### Email Preferences
[User's preferred email handling patterns]
"""

SCRIPTS: dict[str, str] = {}

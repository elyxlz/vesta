"""Email skill template."""

SKILL_MD = """\
---
name: email
description: This skill should be used when the user asks about "email", "emails", "inbox", "messages", or needs to read/send emails, reply to messages, or manage email communications.
---

# Email

You have access to email tools through MCP. Use them to help the user manage their email communications.

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

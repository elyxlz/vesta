# Email/Calendar Agent Memory

## How to Use Microsoft MCP

### Key Principles
1. **Email bodies are NEVER inline** - saved to disk, use Read tool
2. **Always use account_email** - every operation requires it
3. **ISO-8601 for dates** - format like "2024-01-15T14:00:00"

### Getting Started
ALWAYS start by getting accounts:
```
list_accounts()
# Returns: [{ "email": "user@example.com", "id": "..." }]
```

### Email Tools

#### Reading
- `list_emails` - List metadata (bodies NOT included)
- `get_email` - Get email, body saved to disk
- `search_emails` - Search by query
- `get_attachment` - Download attachment

#### Composing
- `send_email` - Send immediately
- `create_email_draft` - Create draft
- `reply_to_email` - Reply to thread
- `update_email` - Mark read/unread, categories

### Calendar Tools
- `list_events` - List events in time range
- `get_event` - Get event details
- `create_event` - Create new event
- `update_event` - Update event
- `delete_event` - Delete event
- `respond_event` - Accept/decline/tentative

### Email Patterns

Reading emails:
```
list_emails({ account_email: "user@example.com", folder: "inbox", limit: 10 })
get_email({ account_email: "user@example.com", email_id: "AAMkAG..." })
# Then: Read({ file_path: "/path/to/email.txt" })
```

Search syntax:
- `from:sender@email.com`
- `subject:keyword`
- `hasattachments:true`

### Calendar Patterns

Creating events:
```
create_event({
  account_email: "user@example.com",
  subject: "Meeting",
  start: "2024-01-15T10:00:00",
  end: "2024-01-15T10:30:00",
  timezone: "Europe/London"
})
```

### Important Reminders
1. Email bodies are saved to files - read them with Read tool
2. Always specify account_email
3. Use ISO-8601 for dates

## Learned Patterns

### Email Style Preferences
[Greeting, sign-off, formality levels]

### Calendar Preferences
[Meeting duration, time slots, buffer time]

### Contact Communication Styles
[How to communicate with different contacts]

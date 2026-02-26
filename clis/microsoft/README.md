# Microsoft MCP

Powerful MCP server for Microsoft Graph API - an AI assistant toolkit focused on Outlook Mail and Calendar.

## Features

- **Email Essentials**: List folders, read messages, create drafts, send/reply, search, and download attachments
- **Calendar Basics**: View upcoming events, fetch event details, create or update meetings, respond or delete invites
- **Multi-Account Ready**: Switch between multiple Microsoft accounts by passing the desired `account_email` to each tool

## Quick Start with Claude Desktop

```bash
# Add Microsoft MCP server (replace with your Azure app ID)
claude mcp add microsoft-mcp -e MICROSOFT_MCP_CLIENT_ID=your-app-id-here -- uvx --from git+https://github.com/elyxlz/microsoft-mcp.git microsoft-mcp

# Start Claude Desktop
claude
```

### Usage Examples

```bash
# Email examples
> read my latest emails (save the bodies to files for review)
> reply to the email from John saying "I'll review this today"
> send an email with attachment to alice@example.com

# Calendar examples  
> show my calendar for next week
> check if I'm free tomorrow at 2pm
> create a meeting with Bob next Monday at 10am

# Multi-account
> list all my Microsoft accounts
> send email from my work account
```

## Available Tools

### Auth Tools
- **`list_accounts`** - Show authenticated Microsoft accounts with their emails and IDs
- **`authenticate_account`** - Start device-code authentication for a new Microsoft account
- **`complete_authentication`** - Finish the device-code flow using the cached response from `authenticate_account`

### Email Tools
- **`list_emails`** - List emails from a folder (metadata + previews only)
- **`get_email`** - Get a specific email; full body is saved to disk automatically and never returned inline
- **`create_email_draft`** - Create a draft with optional attachments
- **`send_email`** - Send an email immediately with CC and attachments
- **`reply_to_email`** - Reply to a message (`reply_all=True` to reach all recipients)
- **`update_email`** - Mark emails as read/unread or update categories
- **`get_attachment`** - Download an attachment to a file path you choose
- **`search_emails`** - Search emails by query (metadata/previews only)

Note: Email bodies are never returned inline. When you call `get_email`, the body is saved to an `emails/` subdirectory next to the data dir, and the tool returns the file path plus helpful warnings if the content is large so you can grep/crop before sharing.

### Calendar Tools
- **`list_events`** - List calendar events in a time window
- **`get_event`** - Get specific event details
- **`create_event`** - Create events with optional location, attendees, and body text
- **`update_event`** - Reschedule or modify existing events
- **`delete_event`** - Cancel events (optionally send cancellation notices)
- **`respond_event`** - Accept/decline/tentatively accept invitations

## Manual Setup

### 1. Azure App Registration

1. Go to [Azure Portal](https://portal.azure.com) → Microsoft Entra ID → App registrations
2. New registration → Name: `microsoft-mcp`
3. Supported account types: Personal + Work/School
4. Authentication → Allow public client flows: Yes
5. API permissions → Add these delegated permissions:
   - Mail.ReadWrite
   - Calendars.ReadWrite
   - Files.ReadWrite
   - Contacts.Read
   - People.Read
   - User.Read
6. Copy Application ID

### 2. Installation

```bash
git clone https://github.com/elyxlz/microsoft-mcp.git
cd microsoft-mcp
uv sync
```

### 3. Authentication

```bash
# Set your Azure app ID
export MICROSOFT_MCP_CLIENT_ID="your-app-id-here"

# Run authentication script
uv run authenticate.py

# Follow the prompts to authenticate your Microsoft accounts
```

### 4. Claude Desktop Configuration

Add to your Claude Desktop configuration:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "microsoft": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/elyxlz/microsoft-mcp.git", "microsoft-mcp"],
      "env": {
        "MICROSOFT_MCP_CLIENT_ID": "your-app-id-here"
      }
    }
  }
}
```

Or for local development:

```json
{
  "mcpServers": {
    "microsoft": {
      "command": "uv",
      "args": ["--directory", "/path/to/microsoft-mcp", "run", "microsoft-mcp"],
      "env": {
        "MICROSOFT_MCP_CLIENT_ID": "your-app-id-here"
      }
    }
  }
}
```

## Multi-Account Support

Each tool accepts an `account_email` argument so you can explicitly choose which mailbox/calendar to operate on:

```python
# Fetch the available accounts
accounts = list_accounts()
work_account_email = accounts[0]["email"]

# Use that email with any tool
send_email(account_email=work_account_email, to=["user@example.com"], subject="Subject", body="Body")
list_emails(account_email=work_account_email, limit=10)
create_event(
    account_email=work_account_email,
    subject="Meeting",
    start="2024-01-15T10:00:00Z",
    end="2024-01-15T11:00:00Z",
)
```

## Development

```bash
# Run tests
uv run pytest tests/ -v

# Type checking
uv run pyright

# Format code
uvx ruff format .

# Lint
uvx ruff check --fix --unsafe-fixes .
```

## Example: AI Assistant Scenarios

### Smart Email Management
```python
accounts = list_accounts()
account_email = accounts[0]["email"]

# List latest emails (previews only)
emails = list_emails(account_email=account_email, limit=10)

# Reply (or reply-all) in the existing thread
reply_to_email(account_email=account_email, email_id=emails[0]["id"], body="Thanks! I'll review today.", reply_all=True)

# Save full content + attachments locally
email = get_email(account_email=account_email, email_id=emails[0]["id"])
with open(email["body_saved_to"], "r", encoding="utf-8") as fh:
    full_body = fh.read()
attachments = [
    get_attachment(
        account_email=account_email,
        email_id=email["id"],
        attachment_id=att["id"],
        save_path=f"/tmp/{att['name']}",
    )
    for att in email.get("attachments", [])
]
send_email(
    account_email=account_email,
    to=["manager@example.com"],
    subject=f"FW: {email['subject']}",
    body=full_body,
    attachments=[att["saved_to"] for att in attachments if "saved_to" in att],
)
```

### Calendar Coordination
```python
accounts = list_accounts()
account_email = accounts[0]["email"]

# Review upcoming events
events = list_events(account_email=account_email, days_ahead=7)

# Create and later update a meeting
event = create_event(
    account_email=account_email,
    subject="Project Review",
    start="2024-01-15T14:00:00Z",
    end="2024-01-15T15:00:00Z",
    location="Conference Room A",
    attendees=["colleague@example.com"],
)

update_event(
    account_email=account_email,
    event_id=event["id"],
    updates={"subject": "Project Review (Updated)", "start": "2024-01-15T15:00:00Z", "end": "2024-01-15T16:00:00Z"},
)
```

## Security Notes

- Tokens are cached inside the provided `--data-dir` (e.g., `<data-dir>/auth_cache.bin`)
- Use app-specific passwords if you have 2FA enabled
- Only request permissions your app actually needs
- Consider using a dedicated app registration for production

## Troubleshooting

- **Authentication fails**: Check your CLIENT_ID is correct
- **"Need admin approval"**: Use `MICROSOFT_MCP_TENANT_ID=consumers` for personal accounts
- **Missing permissions**: Ensure all required API permissions are granted in Azure
- **Token errors**: Delete `auth_cache.bin` inside your configured `--data-dir` and re-authenticate

## License

MIT

"""WhatsApp skill template."""

SKILL_MD = """\
---
name: whatsapp
description: This skill should be used when the user asks about "WhatsApp", "message", "text", "chat", "send a message", or needs to send/receive WhatsApp messages, manage contacts, or interact with WhatsApp groups.
---

# WhatsApp

You have access to WhatsApp via the `~/whatsapp` CLI. Use it to help the user communicate via WhatsApp.

## Setup

### Prerequisites

Install Go (if not already installed):
```bash
apt-get install -y golang
```

Build the CLI:
```bash
cd {install_root}/clis/whatsapp && go build -o ~/whatsapp .
```

The binary is at `~/whatsapp`.

### Authentication Flow

1. Check status: `~/whatsapp authenticate` → `{{"status":"not_started"}}`
2. Start server: `~/whatsapp serve &`
3. Wait 3s, check again: `~/whatsapp authenticate` → `{{"status":"qr_ready","qr_terminal":"..."}}`
4. Show the `qr_terminal` value to the user: "Scan this QR code with WhatsApp on your phone"
5. Poll every 5s: `~/whatsapp authenticate` → `{{"status":"authenticated"}}`
6. Confirm success to the user

## Commands

```bash
# Check authentication status (no connection needed)
~/whatsapp authenticate

# Send a message (by contact name, phone, or group)
~/whatsapp send-message --to "Mom" --message "On my way!"
~/whatsapp send-message --to "+44123456789" --message "Hello"

# Send a file
~/whatsapp send-file --to "Mom" --file-path /path/to/photo.jpg --caption "Check this out"

# List recent chats
~/whatsapp list-chats --limit 20

# List messages from a chat
~/whatsapp list-messages --to "Mom" --limit 20
~/whatsapp list-messages --to "Mom" --after "2025-11-01T00:00:00Z" --before "2025-11-15T00:00:00Z"

# Search messages
~/whatsapp list-messages --query "dinner" --limit 10

# List/search contacts
~/whatsapp list-contacts --limit 50
~/whatsapp search-contacts --query "John" --limit 10

# Add/remove contacts
~/whatsapp add-contact --name "John Smith" --phone "+44123456789"
~/whatsapp remove-contact --identifier "John Smith"

# Download media from a message
~/whatsapp download-media --message-id <msg_id> --to "Mom" --download-path /tmp/media.jpg

# React to a message
~/whatsapp send-reaction --message-id <msg_id> --to "Mom" --emoji "👍"

# Group management
~/whatsapp list-groups --limit 20
~/whatsapp create-group --name "Trip Planning" +44111111111 +44222222222
~/whatsapp leave-group --group "Old Group"
~/whatsapp update-group-participants --group "Trip Planning" --action add +44333333333
```

## Background Monitoring

Start the listener to get notifications for new messages:
```bash
~/whatsapp serve &
```

## Best Practices

- Always confirm before sending messages to new contacts
- Be concise in messages - match WhatsApp's casual tone
- Check authentication before attempting to send
- Use contact names when possible (more reliable than phone numbers)

### Contact Communication Styles
[How to communicate with different contacts]

### Message Preferences
[User's preferred messaging patterns]
"""

SCRIPTS: dict[str, str] = {}

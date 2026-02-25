# WhatsApp MCP Server (Go Implementation)

This is a pure Go implementation of the WhatsApp Model Context Protocol (MCP) server. It provides direct integration with WhatsApp through the whatsmeow library, eliminating the need for a separate Python layer.

## Features

- **Pure Go Implementation**: Single language, better performance
- **Direct WhatsApp Integration**: No REST API middleman
- **Complete Feature Set**: All 20 tools from the original implementation
- **SQLite Storage**: Message history and chat metadata
- **Media Support**: Send/receive images, videos, audio, and documents
- **Voice Messages**: Automatic Opus conversion with FFmpeg
- **Group Management**: Create, manage, and interact with groups
- **Notifications**: Optional notification system for new messages
- **QR Code Authentication**: Easy setup with WhatsApp mobile app

## Prerequisites

- Go 1.22 or later
- FFmpeg (optional, for voice messages)
- Claude Desktop or Cursor

## Installation

### 1. Build the Server

```bash
cd mcps/whatsapp-mcp-go
go mod download
go build -o whatsapp-mcp
```

### 2. Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "whatsapp": {
      "command": "/path/to/whatsapp-mcp",
      "args": [
        "--data-dir", "/path/to/data/directory",
        "--notifications-dir", "/path/to/notifications/directory"
      ]
    }
  }
}
```

### 3. Configure Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "whatsapp": {
      "command": "/path/to/whatsapp-mcp",
      "args": [
        "--data-dir", "/path/to/data/directory"
      ]
    }
  }
}
```

## First Run

1. Start Claude Desktop or Cursor
2. The WhatsApp integration will appear in the tools list
3. On first run, a QR code will appear in the logs
4. Scan the QR code with WhatsApp mobile:
   - Open WhatsApp on your phone
   - Go to Settings > Linked Devices
   - Tap "Link a Device"
   - Scan the QR code

## MCP Tools Available

### Contact Management
- `add_contact` - Save contact name + phone so you can reference chats before any messages
- `search_contacts` - Search contacts by name or phone number
- `get_contact` - Get contact information by JID
- `update_contact` - Update contact name

### Message Operations
- `list_messages` - Get messages with filters
- `get_message_context` - Get messages around a specific message
- `send_message` - Send text messages
- `send_file` - Send files (images, videos, documents)
- `send_audio_message` - Send voice messages
- `download_media` - Download media from messages
- `send_reaction` - Send emoji reactions

### Chat Management
- `list_chats` - List available chats
- `get_chat` - Get chat metadata
- `get_direct_chat_by_contact` - Find chat by phone number
- `get_contact_chats` - List chats involving a contact
- `get_last_interaction` - Get most recent message with contact

### Group Management
- `create_group` - Create new groups
- `leave_group` - Leave groups
- `list_groups` - List all groups
- `get_group_invite_link` - Get invite links
- `update_group_participants` - Add/remove participants

## Command Line Options

```bash
./whatsapp-mcp --data-dir <path> [--notifications-dir <path>]
```

- `--data-dir` (required): Directory for SQLite databases and WhatsApp session
- `--notifications-dir` (optional): Directory for notification JSON files

## Data Storage

The server stores data in two SQLite databases:

- `whatsapp.db` - WhatsApp session and device information
- `messages.db` - Message history, chats, and contacts

## Audio Message Requirements

To send voice messages, audio files must be in Opus format:

- **With FFmpeg**: Automatic conversion from any audio format
- **Without FFmpeg**: Must provide `.ogg` Opus files manually

Install FFmpeg:
```bash
# macOS
brew install ffmpeg

# Linux
sudo apt-get install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```

## Differences from Python Implementation

### Improvements
- **Single binary**: No Python dependencies
- **Better performance**: Direct database access, no HTTP overhead
- **Simpler deployment**: Single Go binary vs Python + Go bridge
- **Type safety**: Compile-time type checking

### Architecture Changes
- Merged bridge and MCP server into single application
- Removed REST API layer (port 8080 no longer used)
- Direct function calls instead of HTTP requests
- Unified error handling and logging

## Troubleshooting

### Build Issues
```bash
# Ensure Go modules are initialized
go mod tidy

# If SQLite issues on Windows, ensure CGO is enabled
go env -w CGO_ENABLED=1
```

### Authentication Issues
- Delete `whatsapp.db` to reset session
- Ensure phone has internet connection
- Check WhatsApp > Settings > Linked Devices

### Message Sync
- Initial sync may take several minutes
- Check `messages.db` is being populated
- Review logs for any sync errors

## Development

### Project Structure
```
whatsapp-mcp-go/
├── main.go          # Entry point and MCP server
├── whatsapp.go      # WhatsApp client operations
├── storage.go       # SQLite message store
├── tools.go         # MCP tool definitions
├── types.go         # Shared types and structs
├── audio.go         # Audio processing
├── notifications.go # Notification system
└── README.md        # This file
```

### Testing
```bash
# Run with verbose logging
./whatsapp-mcp --data-dir ./data 2>debug.log

# Test specific tool
echo '{"method":"tools/call","params":{"name":"list_chats","arguments":{}}}' | ./whatsapp-mcp --data-dir ./data
```

## Migration from Python Version

If migrating from the Python implementation:

1. The database format is compatible - copy `messages.db`
2. Re-authenticate with WhatsApp (new `whatsapp.db`)
3. Update Claude/Cursor configuration to use Go binary
4. Remove Python dependencies

## Security Notes

- Session data is stored locally in `whatsapp.db`
- Messages are stored unencrypted in `messages.db`
- Keep data directory permissions restricted
- Consider encryption for sensitive deployments

## License

This implementation uses:
- [whatsmeow](https://github.com/tulir/whatsmeow) - MIT License
- [go-sqlite3](https://github.com/mattn/go-sqlite3) - MIT License
- [MCP Go SDK](https://github.com/modelcontextprotocol/go-sdk) - MIT License

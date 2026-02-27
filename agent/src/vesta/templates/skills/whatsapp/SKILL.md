---
name: whatsapp
description: This skill should be used when the user asks about "whatsapp", "message", "text", "chat", or needs to send/receive messages via WhatsApp.
---

# WhatsApp — CLI: whatsapp

## Setup

1. Build the WhatsApp CLI and add to PATH:
   ```bash
   cd {install_root}/tools/whatsapp && go build -o /usr/local/bin/whatsapp .
   ```
2. Authenticate (file-based — reads local auth state):
   ```bash
   whatsapp authenticate
   ```
   If not authenticated, a QR code image is saved to `~/data/whatsapp/qr-code.png`.
   Serve it on port 7865 (the only port exposed to the host):
   ```bash
   cd ~/data/whatsapp && uv run python3 -m http.server 7865 &
   ```
   Then tell the user to open `http://localhost:7865/qr-code.png` in their browser.
   Kill the HTTP server after the user has scanned the code.
   If the QR code expires, kill the daemon (`whatsapp serve`), restart it, and re-run `whatsapp authenticate` to get a fresh QR code.

## Quick Reference
```bash
whatsapp send --to "+1234567890" --message "Hello!"
whatsapp send --to "+1234567890" --message "Photo" --attachment /path/to/image.jpg
whatsapp chats
whatsapp contacts
whatsapp messages --chat-id "<jid>" --limit 20
whatsapp groups
whatsapp react --chat-id "<jid>" --message-id "<id>" --emoji "👍"
whatsapp backfill --chat-id "<jid>"
whatsapp send-file --to "+1234567890" --file /path/to/document.pdf
```

## Notes
- **Message quoting**: Use single quotes for the `--message` argument to avoid bash escaping issues (e.g. `--message 'hello!'` not `--message "hello\!"`)
- Phone numbers must include country code with `+` prefix
- Chat IDs are JIDs (e.g., `1234567890@s.whatsapp.net`)
- Group IDs end with `@g.us`
- The binary is installed to `/usr/local/bin/whatsapp`
- Auth state is stored in `~/data/whatsapp/`

## Background: `whatsapp serve &`

### Contact Preferences
[How the user prefers to communicate with different contacts]

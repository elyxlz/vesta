---
name: whatsapp
description: This skill should be used when the user asks about "whatsapp", "message", "text", "chat", or needs to send/receive messages via WhatsApp. IMPORTANT — this skill requires a background daemon. Before doing anything, immediately make sure the daemon is running. Read this skill to learn how.
---

# WhatsApp — CLI: whatsapp

## Setup

1. Install dependencies (gcc for CGO, and Go from https://go.dev/dl/ — NOT the system package manager):
   ```bash
   apt-get install -y gcc
   ARCH=$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')
   curl -fsSL "https://go.dev/dl/$(curl -fsSL 'https://go.dev/VERSION?m=text' | head -1).linux-${ARCH}.tar.gz" | tar -C /usr/local -xz
   export PATH="/usr/local/go/bin:$PATH"
   ```
2. Build the WhatsApp CLI (CGO required for SQLite):
   ```bash
   cd {install_root}/tools/whatsapp && CGO_ENABLED=1 go build -o /usr/local/bin/whatsapp .
   ```
3. Start the daemon and authenticate:
   ```bash
   whatsapp serve &
   sleep 3
   whatsapp authenticate
   ```
   **Before showing the QR code**, confirm with the user that they should scan it from a dedicated WhatsApp account for the assistant — NOT their personal WhatsApp. This can be a throwaway phone with a new SIM, a work profile (Android) WhatsApp with an eSIM, or any separate number. Scanning from their personal account would link their own WhatsApp to Vesta and she'd be reading/sending from their personal chats.

   If not authenticated, a QR code image is saved to `~/data/whatsapp/qr-code.png`.
   Serve it on any available port (host network is shared):
   ```bash
   cd ~/data/whatsapp && uv run python3 -m http.server 8888 &
   ```
   Tell the user to open `http://localhost:8888/qr-code.png` and scan immediately.

   **QR codes expire in ~20 seconds.** Warn the user to have WhatsApp ready before opening the link.

   After the user says they scanned, wait 10 seconds then check:
   ```bash
   sleep 10 && whatsapp authenticate
   ```
   **NEVER restart the daemon after the user has scanned** — restarting invalidates the session. If `authenticate` still says not authenticated, wait longer and check again (up to 30 seconds). Only restart the daemon if the user confirms they didn't scan in time or the QR visually expired.

   Kill the HTTP server once authenticated.

## Quick Reference
```bash
whatsapp send '+1234567890' 'Hello!'
whatsapp send '+1234567890' 'Photo' --attachment /path/to/image.jpg
whatsapp chats
whatsapp contacts
whatsapp messages --chat-id "<jid>" --limit 20
whatsapp groups
whatsapp react --chat-id "<jid>" --message-id "<id>" --emoji "👍"
whatsapp backfill --chat-id "<jid>"
whatsapp send-file --to "+1234567890" --file /path/to/document.pdf
```

## Notes
- Phone numbers must include country code with `+` prefix
- Chat IDs are JIDs (e.g., `1234567890@s.whatsapp.net`)
- Group IDs end with `@g.us`
- The binary is installed to `/usr/local/bin/whatsapp`
- Auth state is stored in `~/data/whatsapp/`

## Background: `whatsapp serve &`

### Contact Preferences
[How the user prefers to communicate with different contacts]

"""WhatsApp skill template."""

SKILL_MD = """\
---
name: whatsapp
description: This skill should be used when the user asks about "WhatsApp", "message", "text", "chat", "send a message", or needs to send/receive WhatsApp messages, manage contacts, or interact with WhatsApp groups.
---

# WhatsApp — CLI: ~/whatsapp

## Quick Reference
```bash
~/whatsapp send "Mom" "On my way!"
~/whatsapp messages "Mom"
~/whatsapp messages "Mom" --limit 20 --after "2025-11-01T00:00:00Z"
~/whatsapp chats
~/whatsapp contacts
~/whatsapp groups
~/whatsapp file "Mom" /path/to/photo.jpg --caption "Check this out"
```

## Other Commands
```bash
~/whatsapp messages --query "dinner" --limit 10
~/whatsapp add-contact "John Smith" "+44123456789"
~/whatsapp remove-contact "John Smith"
~/whatsapp download-media --message-id <id> --to "Mom"
~/whatsapp react "Mom" <message_id> "👍"
~/whatsapp create-group --name "Trip" +44111111111 +44222222222
~/whatsapp leave-group "Old Group"
~/whatsapp update-group-participants --group "Trip" --action add +44333333333
```

## Setup (first time)
```bash
apt-get install -y golang
cd {install_root}/clis/whatsapp && go build -o ~/whatsapp .
```

## Authentication
1. `~/whatsapp serve &` then wait 3s
2. `~/whatsapp authenticate` → check status
3. If `qr_ready`: serve the image so user can scan from any device:
   `mkdir -p /tmp/serve && cp ~/data/whatsapp/qr-code.png /tmp/serve/qr.png && python3 -m http.server 7865 --directory /tmp/serve &`
4. Poll `~/whatsapp authenticate` every 5s until `authenticated`, then `kill %1; rm -rf /tmp/serve`

## Background: ~/whatsapp serve &

### Contact Communication Styles
[How to communicate with different contacts]

### Message Preferences
[User's preferred messaging patterns]
"""

SCRIPTS: dict[str, str] = {}

---
name: file-host
description: Host files over HTTP so they can be shared with the user or others by link (PDFs, images, exports, a live QR for device linking). Serves a directory; pair with a public vestad service for a shareable URL.
---

# file-host

Serve a directory of files over HTTP and hand someone a link. Use when the user needs to download or view something you produced or fetched (a PDF, an export, a screenshot), or when another skill needs a public URL for a file (e.g. a WhatsApp/Signal linking QR).

## Serve a file and get a shareable link (on vesta)

The server binds to localhost, so it needs a public route.

```bash
# 1. drop the file(s) into the served directory
mkdir -p ~/.file-host && cp /path/to/report.pdf ~/.file-host/

# 2. register a public service (idempotent: returns the same port each time)
PORT=$(~/agent/skills/vestad/scripts/register-service file-host --public)

# 3. serve it (run in a screen so it persists)
screen -dmS file-host python3 ~/agent/skills/file-host/serve.py --dir ~/.file-host --port "$PORT"
```

Shareable URL: `$VESTAD_TUNNEL/agents/$AGENT_NAME/file-host/<filename>` (public route, no token needed).

Off vesta, bind any port with `serve.py --port N` and expose it with your own tunnel/ssh.

## Flags

- `--dir DIR`: directory to serve (default `~/.file-host`).
- `--port N`: port to bind on `127.0.0.1` (default 8770; on vesta use the port from the service registration).
- `--no-cache`: send `Cache-Control: no-store` on every response. Use when serving a file that is rewritten in place, e.g. a rotating QR image, so browsers always re-fetch the current version.

## Rules

- **Public means public.** Anything in the served directory is reachable by anyone with the URL (the route has no auth). Never host secrets, credentials, or sensitive personal documents unless the user explicitly asked you to share that exact file, and use an unguessable filename when sharing anything personal.
- **Clean up.** Remove files from the served directory once the user has them, and stop the screen (`screen -S file-host -X quit`) when no longer needed.
- **Persist it** by adding the serve command to the `## Daemons` section of `~/agent/skills/restart/SKILL.md` if you want it always available.

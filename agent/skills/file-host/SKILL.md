---
name: file-host
description: Host files over HTTP so they can be shared with the user or others by link (PDFs, images, exports, a live QR for device linking). Serves a directory; pair with a public vestad service for a shareable URL.
---

# file-host

Serve a directory of files over HTTP and hand someone a link. Use when the user needs to download or view something you produced or fetched (a PDF, an export, a screenshot), or when another skill needs a public URL for a file (e.g. a WhatsApp/Signal linking QR).

## Serve a file and get a shareable link (on vesta)

The server has no auth of its own, so it is reached through a public vestad route rather than directly.

```bash
# 1. put the command on PATH (the daemon and its restart line call it by name)
mkdir -p ~/.local/bin && ln -sf ~/agent/skills/file-host/file-host ~/.local/bin/file-host

# 2. drop the file(s) into the served directory
mkdir -p ~/.file-host && cp /path/to/report.pdf ~/.file-host/

# 3. serve it
file-host daemon start
```

Shareable URL: `$VESTAD_TUNNEL/agents/$AGENT_NAME/file-host/<filename>` (public route, no token needed).

Off vesta, bind any port with `serve.py --port N` and expose it with your own tunnel/ssh.

## Flags

- `--dir DIR`: directory to serve (default `~/.file-host`).
- `--port N`: port to bind on `0.0.0.0` (default 8770; on vesta `file-host daemon start` supplies the port vestad assigned).
- `--no-cache`: send `Cache-Control: no-store` on every response. Use when serving a file that is rewritten in place, e.g. a rotating QR image, so browsers always re-fetch the current version.

## Rules

- **Public means public.** Anything in the served directory is reachable by anyone with the URL (the route has no auth). Never host secrets, credentials, or sensitive personal documents unless the user explicitly asked you to share that exact file, and use an unguessable filename when sharing anything personal.
- **Clean up.** Remove files from the served directory once the user has them, and run `file-host daemon stop` when no longer needed.
- **Persist it** by registering the serve command for restart as `~/agent/skills/restart/SKILL.md` describes, if you want it always available.

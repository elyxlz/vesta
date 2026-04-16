---
name: ssh
description: Use when the user wants to allow another computer to SSH into this machine, share remote access, or set up a public SSH tunnel. Creates an internet-accessible SSH endpoint via bore.
---

# SSH Access

Expose this machine's SSH server publicly over the internet using [bore](https://github.com/ekzhang/bore), a lightweight TCP tunnel. No account required. Standard SSH clients work on the other end — no special tooling needed.

## Usage

```bash
# Start the tunnel (downloads bore if needed, runs in background)
~/vesta/skills/ssh/scripts/start.sh

# Check status and get the current connection command
~/vesta/skills/ssh/scripts/status.sh

# Stop the tunnel
~/vesta/skills/ssh/scripts/stop.sh
```

## Notes

- The tunnel endpoint changes each time `start.sh` is run (bore assigns a random port)
- The tunnel connects to port 22 on this machine (the host SSH server, accessible via host networking)
- The other machine connects with: `ssh <username>@bore.pub -p <port>`
- Tunnel runs in a `screen` session named `bore-ssh`
- bore.pub is the default relay; it's a public free service — don't tunnel anything sensitive without considering this

---
name: skills-registry
description: Discover and install new capabilities from the GitHub skill registry.
---

# Skills Manager

Vesta's skills come from a registry on GitHub (`agent/skills/`). You can search for new skills and install them on demand. Installed skills are activated on the next restart.

## Search the registry

```bash
~/agent/skills/skills-registry/scripts/skills-search                  # list all available skills
~/agent/skills/skills-registry/scripts/skills-search email            # search by keyword
```

## Install a skill

```bash
~/agent/skills/skills-registry/scripts/skills-install <name>
```

After installing, restart yourself with the `restart_vesta` tool to load the new skill into context.

## Check what's installed

```bash
ls ~/agent/skills/
```

## Registering a background service

Skills that run a daemon register it with vestad to get a port, then start it. The
`register-service` helper does the curl and prints the port (idempotent: same port per name):

```bash
# token-only service
PORT=$(~/agent/skills/skills-registry/scripts/register-service tasks)
# public service (reachable through the tunnel without a token)
PORT=$(~/agent/skills/skills-registry/scripts/register-service dashboard --public)
```

So the service comes back after a container restart, add its startup command to the
`## Services` section of `~/agent/skills/restart/SKILL.md`, one fenced block per skill. Use a
single line that re-registers and starts, e.g.:

```bash
PORT=$(~/agent/skills/skills-registry/scripts/register-service tasks) && screen -dmS tasks tasks serve --notifications-dir ~/agent/notifications --port $PORT
```

## Notes

- Skills are installed via git sparse checkout from the upstream repo
- Installed skills receive updates automatically during upstream sync merges
- Core skills ship pre-installed; optional skills are checked out on demand
- After installing a skill that requires setup, read its `SETUP.md`

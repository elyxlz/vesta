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

## Notes

- Skills are installed via git sparse checkout from the upstream repo
- Installed skills receive updates automatically during upstream sync merges
- Core skills ship pre-installed; optional skills are checked out on demand
- After installing a skill that requires setup, read its `SETUP.md`

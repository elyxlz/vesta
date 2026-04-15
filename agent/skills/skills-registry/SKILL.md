---
name: skills-registry
description: Discover and install new capabilities from the skill registry. Use this when asked to add a new feature, when you want to explore what you could do, or when a user asks if you can do something you don't have a skill for yet. The registry lives on GitHub. Search it to find skills, then install them to give yourself new abilities.
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

- Skills you install are downloaded from `agent/skills/` in the GitHub repo
- Core skills ship pre-installed; optional skills are downloaded on demand
- After installing a skill that requires setup, read its `SETUP.md`

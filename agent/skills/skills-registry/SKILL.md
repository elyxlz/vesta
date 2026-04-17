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

## Uninstall a skill

```bash
~/agent/skills/skills-registry/scripts/skills-uninstall <name>
```

This removes the skill from git sparse checkout so it no longer appears in the working tree or upstream diffs.

## Check what's installed

```bash
ls ~/agent/skills/
```

## Sparse checkout layout

The agent's git working tree uses a **restrictive sparse checkout** — only `agent/` is tracked, with bind-mounted paths excluded and all skills excluded by default. Each installed skill is added as an explicit inclusion:

```
agent/
!agent/core/
!agent/pyproject.toml
!agent/uv.lock
!agent/skills/*/
agent/skills/tasks/
agent/skills/whatsapp/
... (one line per installed skill)
```

This keeps upstream diffs clean: only files the agent actually uses appear in `git diff FETCH_HEAD..HEAD`. The vestad daemon sets up this base config when creating a new agent container; `skills-install` and `skills-uninstall` manage individual skill entries.

## Notes

- Skills are installed via git sparse checkout from the upstream repo
- Installed skills receive updates automatically during upstream sync merges
- Core skills ship pre-installed; optional skills are checked out on demand
- After installing a skill that requires setup, read its `SETUP.md`

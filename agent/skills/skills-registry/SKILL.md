---
name: skills-registry
description: Discover and install new capabilities from the GitHub skill registry.
---

# Skills Manager

Vesta's skills come from a registry on GitHub (`agent/skills/`).

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

## Installing or updating a skill's CLI

Many skills ship a command line tool in `cli/`. Install it, or reinstall it after
you edit it, as an editable `uv` tool. That links the command to its source, so
your edits and upstream updates take effect on the command's next run:

```bash
uv tool install --editable ~/agent/skills/<name>/cli
```

Never install a skill's CLI with `uv pip install -e` or `pip install -e`. Run from
`~/agent` those resolve the engine venv, dropping the skill's command into
`~/agent/.venv/bin`, which leads your PATH and shadows the real tool: the command
and its daemon then break with an import error. `uv tool install` keeps the CLI
isolated and on `~/.local/bin`, so use it every time.

## Notes

- Skills are installed via git sparse checkout from the upstream repo
- Installed skills receive updates automatically during upstream sync
- Core skills ship pre-installed; optional skills are checked out on demand
- After installing a skill that requires setup, read its `SETUP.md`

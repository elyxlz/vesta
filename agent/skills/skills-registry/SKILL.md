---
name: skills-registry
description: Discover and install new capabilities from the local skill registry.
---

# Skills Manager

Every Vesta skill ships on disk under `~/agent/skills/`. Installing one doesn't download
anything; it activates the skill (links it so you can use it). Uninstalling deactivates it.

## Search the registry

```bash
~/agent/skills/skills-registry/scripts/skills-search                  # list all available skills
~/agent/skills/skills-registry/scripts/skills-search email            # search by keyword
```

Installed skills are marked `[installed]`.

## Install a skill

```bash
~/agent/skills/skills-registry/scripts/skills-install <name>
```

After installing, restart yourself with the `restart_vesta` tool to load the new skill into context.

## Check what's installed

```bash
cat ~/agent/data/installed-skills.txt
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

- A skill is activated by linking it into `~/.claude/skills` (see `link-skills.sh`); its files are always on disk
- Installed skills receive updates automatically during upstream sync
- Core skills are always active; optional skills are activated on demand
- After installing a skill that requires setup, read its `SETUP.md`

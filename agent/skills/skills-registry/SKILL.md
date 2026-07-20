---
name: skills-registry
description: Discover and activate new capabilities from the local skill registry.
---

# Skills Manager

Every Vesta skill ships on disk under `~/agent/skills/`. There is no download step: a skill
is either active (linked so you can use it) or inactive. Activating one links it; deactivating
one unlinks it.

## Search the registry

```bash
~/agent/skills/skills-registry/scripts/skills-search                  # list all available skills
~/agent/skills/skills-registry/scripts/skills-search email            # search by keyword
```

Active skills are marked `[active]`.

## Activate a skill

```bash
~/agent/skills/skills-registry/scripts/skills-activate <name>
```

After activating, restart yourself with the `restart_vesta` tool to load the new skill into context.

## Deactivate a skill

```bash
~/agent/skills/skills-registry/scripts/skills-deactivate <name>
```

## Check what's active

```bash
cat ~/agent/data/active-skills.txt
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
- Active skills receive updates automatically during upstream sync
- Core skills are always active; optional skills are activated on demand
- After activating a skill that requires setup, read its `SETUP.md`

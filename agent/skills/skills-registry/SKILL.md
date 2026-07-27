---
name: skills-registry
description: Discover and activate capabilities from the local skill registry, and build a new skill of your own.
---

# Skills Manager

Every Vesta skill ships on disk under `~/agent/skills/`. There is no download step: a skill
is either active (linked so you can use it) or inactive. Activating one records it for the
next restart; deactivating one removes that record.

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
python3 -m json.tool ~/agent/data/config.json | sed -n '/"active_skills"/,/]/p'
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

## Building a new skill

A skill is a directory under `~/agent/skills/<name>/` holding a `SKILL.md`, plus whatever
scripts it needs. Nothing indexes it, so creating the directory is the whole install.

`SKILL.md` opens with YAML frontmatter:

```markdown
---
name: tricount
description: Shared expenses and group balances; add an expense, settle up, see who owes what.
---

# Tricount (CLI: tricount)

<what you read when the skill activates: commands, examples, gotchas>
```

The `description` is discovery text: it decides whether you open the skill at all, so write when
to reach for it and what triggers it, never a summary of its steps. An agent that can read the
workflow from the description follows that instead of opening the body.

Put a command line tool in `cli/` as its own standalone project (`cli/pyproject.toml`), install it
with `uv tool install --editable` as above, and keep setup that runs once (auth, credentials,
model downloads) in a `SETUP.md` beside `SKILL.md`.

**If the skill runs a background process**, do not write your own `screen` line. Every daemon in
the fleet is driven the same way, `<skill> daemon start|stop|restart|status`, delegating to
`~/agent/skills/vestad/scripts/daemon-lifecycle`, which owns the guard against duplicates, the
port registration, waiting until the daemon is actually up, and stopping it cleanly. A skill with
a CLI adds a `daemon` subcommand; a skill without one adds a `scripts/daemon` wrapper plus a
launcher of the skill's own name on PATH. Read the `vestad` skill for the flag list and a worked
example, including the two things the runner cannot work out for itself: a daemon that ignores
SIGHUP has to hand over its pid file, and a daemon that reports its own death has to recognize a
deliberate stop.

Then add the guarded startup line yourself to the `## Daemons` section of the `restart` skill, so
the daemon comes back after a container restart.

Skills you build are yours until you file them: the `upstream-pr` skill contributes anything
general back so every Vesta gets it.

## Notes

- A skill is activated by listing it in `active_skills` in `~/agent/data/config.json`; the boot entrypoint links it into `~/.claude/skills`
- Active skills receive updates automatically during upstream sync
- Core skills are always active; optional skills are activated on demand
- After activating a skill that requires setup, read its `SETUP.md`

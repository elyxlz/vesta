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

A skill puts a command on PATH one of two ways, and which one is decided by dependencies. A command
that needs third-party packages lives in `cli/` as its own standalone uv project (`cli/pyproject.toml`
+ `cli/uv.lock`), which gives it an isolated venv; its `[project.scripts]` names every command it
installs, one line each, so a skill that needs several commands declares several there, and
`uv tool install --editable` (as above) puts them all on PATH. A command that needs no third-party
packages, a stdlib-only script or a shell script, is a single executable at
`~/agent/skills/<skill>/<skill>` that agent startup links, with no venv and no install step. Nothing
else belongs on PATH: a wrapper copied into a system `bin`, or a runtime environment built by hand,
sits outside both mechanisms and no boot step maintains it. Copy a `cli/` project's shape from an
existing skill such as `tasks`, and keep setup that runs once (auth, credentials, model downloads) in
a `SETUP.md` beside `SKILL.md`.

**If the skill runs a background process**, it implements the daemon contract in its own
language: one command named after the skill, with `daemon start|stop|restart|status` as verbs on
it, each printing one line of JSON, a pid and port record under `~/agent/data/daemons/`, a log at
`~/agent/logs/<skill>.log`, an idempotent start that returns only once the daemon is up, and
SIGTERM as the deliberate stop. A skill with a CLI declares the daemon in a `daemon` subcommand;
a skill without one is a single executable at `~/agent/skills/<skill>/<skill>`, which agent
startup puts on PATH. The `vestad` skill holds the full spec plus a worked launcher to copy,
including the two obligations that are easy to miss: a daemon that serves a port registers it
itself (private unless the page must load with no credential at all), and a daemon that reports
its own death stays silent when the death was a SIGTERM.

Then add the startup line yourself, the bare `<skill> daemon start`, to the `## Daemons` section
of the `restart` skill, so the daemon comes back after a container restart.

Skills you build are yours until you file them: the `upstream-pr` skill contributes anything
general back so every Vesta gets it.

## Notes

- A skill is activated by listing it in `active_skills` in `~/agent/data/config.json`; the boot entrypoint links it into `~/.claude/skills`
- Active skills receive updates automatically during upstream sync
- Core skills are always active; optional skills are activated on demand
- After activating a skill that requires setup, read its `SETUP.md`

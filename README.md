# Vesta

A personal AI assistant that runs as a persistent daemon in Docker, powered by Claude. It watches for notifications, responds to messages, and autonomously handles tasks across your apps and services.

## What it does

Vesta runs in the background and:

- Processes messages you send it (via stdin or WhatsApp)
- Monitors notification files and reacts proactively
- Performs tasks using a set of built-in skills (email, calendar, reminders, browser, etc.)
- Consolidates memory nightly so it remembers context across sessions

## Prerequisites

- Docker
- A Claude subscription (for `claude login`)

## Getting started

```bash
vesta setup
```

## Management

```
vesta setup      Build image, create container, authenticate Claude
vesta rebuild    Rebuild image and recreate container, preserving auth
vesta start      Start the container
vesta stop       Stop the container
vesta attach     Show recent logs then attach to console
vesta logs       Tail container logs
vesta shell      Open a shell inside the container
vesta backup     Snapshot container state (docker commit)
vesta status     Show container status
vesta destroy    Remove the container
```

## Skills

Skill templates live in `src/vesta/templates/skills/`. Each skill has a `SKILL.md` with setup instructions, CLI usage, and memory sections. Vesta activates skills on demand based on what you ask for.

## How it works

Vesta uses Claude as its reasoning engine. On startup it initializes skill templates and memory into `~/memory/skills/` inside the container. A monitor loop checks for new notifications and triggers proactive responses. Messages from stdin or WhatsApp are processed through Claude with access to all installed skills.

Memory lives in `~/memory/` inside the container. Use `vesta backup` to snapshot container state before major changes.

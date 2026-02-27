# Vesta

A personal AI assistant that runs as a persistent daemon in Docker, powered by Claude. It watches for notifications, responds to messages, and autonomously handles tasks across your apps and services.

## What it does

Vesta runs in the background and:

- Processes messages you send it (via stdin or WhatsApp)
- Monitors notification files and reacts proactively
- Performs tasks using a set of built-in skills (email, calendar, reminders, browser, etc.)
- Consolidates memory nightly so it remembers context across sessions

## Prerequisites

### Linux
- Docker ([install](https://docs.docker.com/engine/install/))
- Claude subscription (for Claude Agent SDK)

### macOS
- macOS 13+ (Ventura or later)
- Claude subscription (for Claude Agent SDK)

### Windows
- WSL2 enabled
- Claude subscription (for Claude Agent SDK)

## Getting started

```bash
vesta setup
```

## Management

```
vesta setup      Create agent, start it, authenticate Claude
vesta rebuild    Snapshot, destroy, recreate from backup
vesta start      Start the agent
vesta stop       Stop the agent
vesta attach     Attach to agent console
vesta logs       Tail agent logs
vesta shell      Open a shell inside the agent
vesta backup     Snapshot agent state (docker commit)
vesta status     Show agent status
vesta destroy    Remove the agent
```

## Architecture

Vesta runs in a Docker container. On Linux, the CLI talks to Docker directly. On macOS, a lightweight Linux VM (via [vfkit](https://github.com/crc-org/vfkit)) hosts Docker. On Windows, a WSL2 distro hosts Docker. The container image is the same across all platforms.

## Skills

Skill templates live in `agent/src/vesta/templates/skills/`. Each skill has a `SKILL.md` with setup instructions, CLI usage, and memory sections. Vesta activates skills on demand based on what you ask for.

## How it works

Vesta uses Claude as its reasoning engine. On startup it initializes skill templates and memory into `~/memory/skills/` inside the container. A monitor loop checks for new notifications and triggers proactive responses. Messages from stdin or WhatsApp are processed through Claude with access to all installed skills.

Memory lives in `~/memory/` inside the container. Use `vesta backup` to snapshot container state before major changes.

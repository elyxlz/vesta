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
# First-time setup: builds image, creates container, authenticates Claude
vesta setup

# Start
vesta start

# Attach to watch it run (detach with Ctrl-Q)
vesta attach
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

Vesta has 10 built-in skills it activates on demand:

| Skill | What it does |
|-------|-------------|
| microsoft | Read, send, search Outlook email and manage calendar events |
| google | Read, send, search Gmail and manage Google Calendar events |
| browser | Web automation via accessibility-tree snapshots and ref-based actions |
| whatsapp | Send and receive WhatsApp messages |
| reminders | Set one-time or recurring reminders |
| todos | Create and track tasks with priorities and due dates |
| onedrive | Browse and manage OneDrive files |
| what-day | Resolve dates to weekdays (prevents scheduling mistakes) |
| report-writer | Generate structured reports |
| keeper | Manage Keeper password vault entries |

## How it works

Vesta uses Claude as its reasoning engine. On startup it initializes skill templates and memory into `~/memory/skills/` inside the container. A monitor loop checks for new notifications and triggers proactive responses. Messages from stdin or WhatsApp are processed through Claude with access to all installed skills.

Memory lives in `~/memory/` inside the container. Use `vesta backup` to snapshot container state before major changes.

# Vesta

A personal AI assistant that runs as a persistent daemon in Docker, powered by Claude. It watches for notifications, responds to messages, and autonomously handles tasks across your apps and services.

---

## What it does

Vesta runs in the background and:

- Processes messages you send it (via stdin or WhatsApp)
- Monitors notification files and reacts proactively
- Performs tasks using a set of built-in skills (email, calendar, reminders, web, etc.)
- Consolidates memory nightly so it remembers context across sessions

---

## Prerequisites

- Docker
- A Claude subscription (for `claude login`)

---

## Getting started

```bash
# 1. Build and set up (builds image, creates container, logs in to Claude)
./vesta setup

# 2. Start
./vesta start

# 3. Attach to watch it run (detach with Ctrl-Q)
./vesta attach
```

That's it. Vesta starts automatically on container start.

---

## Management

```
./vesta setup      Build image, create container, log in to Claude
./vesta start      Start the container
./vesta stop       Stop the container
./vesta attach     Attach to the console
./vesta logs       Stream logs
./vesta shell      Open a shell inside the container
./vesta backup     Save a snapshot (docker commit)
./vesta destroy    Remove the container
```

---

## Skills

Vesta has 9 built-in skills it activates on demand:

| Skill | What it does |
|-------|-------------|
| email | Read, send, search email (Microsoft/Outlook) |
| calendar | Create and manage calendar events |
| browser | Web automation and screenshots via Playwright |
| whatsapp | Send and receive WhatsApp messages |
| reminders | Set one-time or recurring reminders |
| tasks | Create and track tasks |
| onedrive | Browse and manage OneDrive files |
| what-day | Resolve dates to weekdays (prevents scheduling mistakes) |
| report-writer | Generate structured reports |

---

## Configuration

Set environment variables in the container or via Docker to override defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `PROACTIVE_CHECK_INTERVAL` | `60` | Seconds between proactive check-ins |
| `NIGHTLY_MEMORY_HOUR` | `4` | Hour (0–23) to consolidate memory; blank to disable |
| `NOTIFICATION_CHECK_INTERVAL` | `2` | Seconds between notification polls |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `WHATSAPP_GREETING_PROMPT` | (set) | Startup message Vesta sends you via WhatsApp; blank to disable |

---

## How memory works

Skills and memory live in `/root/memory/` inside the container. Use `./vesta backup` to snapshot the container state before major changes. Memory is updated nightly and whenever Vesta learns something worth keeping.

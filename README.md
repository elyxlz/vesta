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

Skills live in `agent/memory/skills/`. Each skill has a `SKILL.md` with setup instructions, CLI usage, and memory sections. Vesta activates skills on demand based on what you ask for.

## CI

CI runs on every push to `master`, every PR, and every version tag (`v*`).

### What runs

| Job | Trigger | What it does |
|-----|---------|-------------|
| **version-check** | always | Validates version is in sync across all 5 source files |
| **build-cli** | always | Builds CLI for linux-x86_64, linux-aarch64, macos-x86_64, macos-aarch64 |
| **test-linux** | always | E2E tests with the linux CLI (create, start, status) |
| **test-macos** | always | Smoke tests + codesign on macOS |
| **build-vm-image** | non-PR | Builds linux VM images (amd64 + arm64) and WSL rootfs |
| **rootfs** | PR only | Lightweight rootfs for Windows e2e |
| **build-test-windows** | always | Builds Windows CLI, imports WSL distro, runs e2e |
| **build-tauri** | non-PR | Builds desktop app (deb, appimage, dmg) |
| **build-tauri-windows** | non-PR | Builds Windows NSIS installer |
| **push-image** | tag only | Pushes Docker image to `ghcr.io` |
| **release** | tag only | Creates GitHub Release with all artifacts |

### Releasing

```bash
./release.sh
```

Reads the version from master and creates a GitHub release. CI builds all artifacts and attaches them.

## Roadmap

- Multi-container / multi-agent support
- Better memory (long-term recall, semantic search, forgetting)
- Thorough testing on macOS and Windows
- Phone number setup in WhatsApp skill
- Evolutionary multi-agent optimization
- Starting templates (pre-configured skill sets)
- Hosted service
- Mobile app
- Backups and importing backups
- Security considerations and hardening

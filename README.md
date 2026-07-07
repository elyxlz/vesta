# Vesta

A personal AI agent that lives in a Docker container, powered by Claude.

Don't want to run a server? [vesta.run](https://vesta.run) hosts one for you. Invite-only.

## Why Vesta

- **Opinionated and easy to set up.** One command to install, one command to start. No gateway, no infrastructure to manage.
- **Self-improving.** Every way Vesta reaches the world (messaging, email, calendars) is a skill Vesta can read and rewrite. Vesta can edit their own source code, write new skills, and fix their own bugs: by default Vesta stays in sync with official updates, but you can let them fully rewrite themselves.
- **1 agent = 1 container.** The Docker container is the state. No external databases, no config drift. Back up the container, restore the container.
- **Agentic bidirectional sync.** Vesta instances can evolve and diverge from the source. Syncing is semantic; the agent understands what changed and why, and merges upstream updates or contributes patches back intelligently.
- **Spreads by invitation.** Your Vesta can walk your friends through getting their own.
- **Secure by default.** You write a constitution that Vesta must follow and can never edit, so your rules always hold. A security layer that screens for prompt-injection attacks and can only be overridden by you is on the roadmap.
- **Built on Claude's own harness.** Benefits from Anthropic RL-maxing their models on it.

## Prerequisites

- Claude subscription or OpenRouter API key
- **Server (vestad)**: Linux with Docker installed
- **Client (CLI & app)**: Linux, macOS, or Windows — no additional dependencies

## Install

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash
```

### Windows

```powershell
irm https://raw.githubusercontent.com/elyxlz/vesta/master/install.ps1 | iex
```

### Install specific components

By default, all available components for your platform are installed. Use flags to install only what you need:

```bash
# CLI only
curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash -s -- --cli

# Server only (Linux)
curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash -s -- --server

# Desktop app only
curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash -s -- --app

# Specific version
curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash -s -- --version=0.1.112
```

Windows (PowerShell):

```powershell
# CLI only
irm https://raw.githubusercontent.com/elyxlz/vesta/master/install.ps1 | iex -- --cli

# Desktop app only
irm https://raw.githubusercontent.com/elyxlz/vesta/master/install.ps1 | iex -- --app
```

## Setup

### 1. Server (Linux)

```bash
vestad
```

On first run, vestad installs a systemd user service, starts itself, and prints the host URL and API key. It runs persistently via systemd (survives logout). A Cloudflare tunnel is set up automatically for remote access.

```bash
vestad status    # show service status
vestad logs      # stream service logs
vestad restart   # restart the service
vestad stop      # stop the service
```

Use `vestad serve --standalone` to run in the foreground without systemd (for CI/development). Use `--no-tunnel` to disable the Cloudflare tunnel.

### 2. Client

Copy the connect link from the server output:

```bash
vesta connect <connect-link>
vesta setup
```

Or in the desktop app, paste the connect link from the server output on the
onboarding screen.

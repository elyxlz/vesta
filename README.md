# Vesta

A personal AI agent that lives in a Docker container, powered by Claude.

## Why Vesta

- **Opinionated and easy to set up.** One command to install, one command to start. No gateway, no infrastructure to manage.
- **Bitter lesson pilled.** No MCP, no gateway. The agent's full source code is editable by itself, including communication channels. Nothing within the docker container is static.
- **Self-improving.** Vesta has a powerful self-improvement core. It can edit its own source code, write new skills, and fix its own bugs.
- **1 agent = 1 container.** The Docker container is the state. No external databases, no config drift. Back up the container, restore the container.
- **Agentic bidirectional sync.** Vesta instances can evolve and diverge from the source. Syncing is semantic; the agent understands what changed and why, and merges upstream updates or contributes patches back intelligently.
- **Self-proliferating.** A Vesta can encourage and help other users onboard and create their own Vestas.
- **Secure by default.** An external supervisor LLM governs security. It follows strict guidelines, only inspects tool calls to avoid prompt injections, and can only be bypassed by user 2FA.
- **Built on Claude Agent SDK.** Benefits from Anthropic's RL on its own harness.

## Prerequisites

- Claude subscription
- **Linux**: Docker
- **macOS**: macOS 13+
- **Windows**: WSL2

## Install

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash
```

### Windows

```powershell
irm https://raw.githubusercontent.com/elyxlz/vesta/master/install.ps1 | iex
```

## Remote Setup

Run vestad on a remote server and connect from your local machine.

### 1. Server

```bash
curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash
vestad serve
```

On startup, vestad prints the host URL and API key. By default it auto-selects an available port and sets up a Cloudflare tunnel. You can pin a specific port with `vestad serve --port 7860` or disable the tunnel with `--no-tunnel`.

### 2. Client

Copy the host URL and API key from the server output:

```bash
vesta connect https://<host>#<api-key>
vesta setup
```

Or in the desktop app, click **connect to server** on the onboarding screen.

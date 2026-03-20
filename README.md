# Vesta

A personal AI agent that lives in a Docker container, powered by Claude.

## Why Vesta

- **Opinionated and easy to set up.** One command to install, one command to start. No gateway, no infrastructure to manage.
- **Bitter lesson pilled.** No MCP, no gateway. The agent's full source code is editable by itself, including communication channels. Very little is hardcoded.
- **Self-improving.** Vesta has a powerful self-improvement core. It can edit its own source code, write new skills, and fix its own bugs.
- **1 agent = 1 container.** The Docker container is the state. No external databases, no config drift. Back up the container, restore the container.
- **Agentic bidirectional sync.** Vesta instances can evolve and diverge from the source. Syncing is semantic — the agent understands what changed and why, and merges upstream updates or contributes patches back intelligently.
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

## Getting started

```bash
vesta setup
```

## How it works

Vesta runs in a Docker container. On Linux, the CLI talks to Docker directly. On macOS, a lightweight Linux VM (via [vfkit](https://github.com/crc-org/vfkit)) hosts Docker. On Windows, a WSL2 distro hosts Docker. The container image is the same across all platforms.

## Commands

```
vesta setup      Create agent, start it, authenticate Claude
vesta start      Start the agent
vesta stop       Stop the agent
vesta attach     Attach to agent console
vesta logs       Tail agent logs
vesta shell      Open a shell inside the agent
vesta backup     Snapshot agent state
vesta rebuild    Recreate agent from backup
vesta status     Show agent status
vesta destroy    Remove the agent
```

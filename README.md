# Vesta

A personal AI assistant that runs as a persistent daemon in Docker, powered by Claude.

## Prerequisites

- Claude subscription
- **Linux**: Docker
- **macOS**: macOS 13+
- **Windows**: WSL2

## Install

### macOS / Linux

Desktop app (includes CLI):
```bash
curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash
```

CLI only:
```bash
curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash -s -- --cli
```

### Windows

Desktop app (includes CLI):
```powershell
irm https://raw.githubusercontent.com/elyxlz/vesta/master/install.ps1 | iex
```

CLI only:
```powershell
irm https://raw.githubusercontent.com/elyxlz/vesta/master/install.ps1 | iex -CliOnly
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

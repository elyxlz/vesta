# Vesta

A personal AI assistant that runs as a persistent daemon in Docker, powered by Claude.

## Prerequisites

- Claude subscription
- **Linux**: Docker
- **macOS**: macOS 13+

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

## Roadmap

- [ ] Better memory (long-term recall, semantic search, forgetting)
- [ ] Auth detection and re-sign-in (handle expired Claude sessions gracefully)
- [ ] Security considerations and hardening
- [ ] Backups and importing backups
- [ ] Thorough testing on macOS and Windows
- [ ] Starting templates (pre-configured skill sets)
- [ ] Phone number setup in WhatsApp skill
- [ ] Telegram skill
- [ ] Multi-container / multi-agent support
- [ ] Evolutionary multi-agent optimization
- [ ] Mobile app
- [ ] Hosted service
- [ ] OpenClaw comparison
- [ ] Blog post

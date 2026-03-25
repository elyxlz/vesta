# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vesta is a personal AI assistant that runs as a persistent daemon in Docker, powered by the Claude Agent SDK. It monitors notifications, responds to messages, and handles tasks autonomously.

## Architecture

Client/server architecture. `vestad` daemon runs on the host (manages Docker containers, serves HTTP+WS API). `vesta` CLI and Tauri desktop app connect to vestad. On macOS Docker runs behind a vfkit VM, on Windows behind WSL2. Python agent runs inside the container.

- **Agent** (`agent/src/vesta/`): Async Python. Entry point `main.py`. Core loop in `core/loops.py` (message processing, notification monitoring). WebSocket server in `api.py`.
- **CLI** (`cli/`): Rust `vesta` client binary. Connects to vestad over HTTPS.
- **Server** (`vestad/`): Rust `vestad` daemon. Manages Docker containers, serves API.
- **Common** (`vesta-common/`): Shared Rust library (types, config, platform setup).
- **Desktop App** (`app/`): Tauri + Svelte. Uses `vesta-common` to connect to vestad.
- **VM** (`vm/`): Dockerfile and scripts for macOS VM and WSL2 images.
- **Tools** (`agent/tools/`): Independent CLI tools. **Never share code between CLIs.**
- **Skills** (`agent/memory/skills/`): Templates also in `agent/src/vesta/templates/skills/`. Each has `SKILL.md` + scripts. No MCP servers.

## Commands

### Agent (run from `agent/`)

```bash
uv run pytest tests/test_unit.py           # Unit tests
uv run pytest tests/test_unit.py::test_foo # Single test
uv run ruff check                          # Lint
uv run ty check                            # Type check
```

### Rust (run from repo root)

```bash
cargo build                                # Build all crates
cargo build -p vesta                       # Build CLI only
cargo build -p vestad                      # Build server only
cargo clippy                               # Lint
cargo test                                 # Test
```

### Releasing

```bash
./release.sh         # Patch release (0.1.0 -> 0.1.1)
./release.sh minor   # Minor release (0.1.0 -> 0.2.0)
./release.sh major   # Major release (0.1.0 -> 1.0.0)
```

Triggers a GitHub Actions workflow that bumps version, commits to master, tags, and creates the release.

**Do NOT bump versions in PRs** — `release.sh` handles version bumps automatically at release time.

## Code Conventions

- **Always `uv run`**, never bare `python`
- **`getattr`, `.get()` (dict), `hasattr` are banned** — use direct access, `in` checks, or try/except
- **No silent exception swallowing** — prefer explicit checks (`if path.exists()`) or log the error
- Minimize comments — only for truly complex logic
- Line length: 144 (ruff)
- `effects.py` exports `get_current_time` as a test seam for time mocking
- `state_dir` defaults to `Path.home()` — the container's home IS the state dir

## CI

Runs on push to `master` and PRs. Checks: version sync across 5 sources (`agent/pyproject.toml`, `Cargo.toml`, `app/src-tauri/Cargo.toml`, `app/src-tauri/tauri.conf.json`, `app/package.json`), ruff, ty, cargo clippy, pytest, `uv.lock` freshness. Releases are triggered by `gh release create` (via `./release.sh`).

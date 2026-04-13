# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vesta is a personal AI assistant that runs as a persistent daemon in Docker, powered by the Claude Agent SDK. It monitors notifications, responds to messages, and handles tasks autonomously.

## Architecture

Client/server architecture. `vestad` daemon runs on the host (manages Docker containers, serves HTTP+WS API). `vesta` CLI and Tauri desktop app connect to vestad. On Linux, the CLI/app bootstraps vestad locally via systemd. On macOS/Windows, users connect to a remote vestad via `vesta connect`. Python agent runs inside the container.

- **Agent** (`agent/src/vesta/`): Async Python. Entry point `main.py`. Core loop in `core/loops.py` (message processing, notification monitoring). WebSocket server in `api.py`.
- **CLI** (`cli/`): Rust `vesta` client binary. Connects to vestad over HTTPS.
- **Server** (`vestad/`): Rust `vestad` daemon. Manages Docker containers, serves API.
- **Desktop App** (`app/`): Tauri + React (TypeScript). Components in `app/src/components/`, providers in `app/src/providers/`.
- **Skills** (`agent/skills/`): Each skill directory has `SKILL.md` + scripts. No MCP servers.

## Commands

### Agent (run from `agent/`)

```bash
uv run pytest tests/ --ignore=tests/test_e2e.py  # Unit tests
uv run pytest tests/test_notifications.py         # Single module
uv run pytest tests/ -k "test_batch"              # Single test by name
uv run pytest skills/tasks/cli/tests/             # Skill CLI tests
uv run ruff check                                 # Lint
uv run ty check                                   # Type check
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

Run locally on master. Bumps versions, updates lockfiles, commits, pushes, and creates the GitHub release. CI then builds artifacts and publishes.

**Do NOT bump versions in PRs** — `release.sh` handles version bumps automatically at release time.

## Code Conventions

### Python (agent/)
- **Always `uv run`**, never bare `python`
- **`getattr`, `.get()` (dict), `hasattr` are banned** — use direct access, `in` checks, or try/except
- **No silent exception swallowing** — prefer explicit checks (`if path.exists()`) or log the error
- Minimize comments — only for truly complex logic
- Line length: 144 (ruff)

### Rust (cli/, vestad/)
- **No panics in library/server code** — return `Result`, never `panic!()` or `.unwrap()` on fallible operations. `.expect()` only where failure is truly impossible.
- **Named constants for magic numbers** — timeouts, buffer sizes, port numbers, retry counts go in `const` at the top of the file.
- **Descriptive variable names** — no single-letter vars (`n`, `t`, `c`). Use `name`, `tag`, `client`.
- **Minimize `.clone()`** — move values into closures when possible, only clone when the value is genuinely needed afterward.
- **Extract repeated patterns** — if 3+ lines appear twice, extract a helper function.

### Frontend (app/src/)
- **"Agent" terminology everywhere** — never "box". Types: `AgentInfo`, `AgentConnection`, `AgentActivityState`.
- **Tauri invoke() names must match Rust backend** — the invoke command strings are the contract, don't rename them.
- **Hook placement** — hooks used only by a single provider live in that provider's folder (e.g. `providers/VoiceProvider/use-voice-input.ts`). `hooks/` is reserved for shared hooks used across multiple components/providers.
- **Components in folders** — each component gets a folder with `index.tsx` and optionally `styles.ts`.

## CI

Runs on push to `master` and PRs. Checks: version sync across 5 sources (`agent/pyproject.toml`, `Cargo.toml`, `app/src-tauri/Cargo.toml`, `app/src-tauri/tauri.conf.json`, `app/package.json`), ruff, ty, cargo clippy, pytest, `uv.lock` freshness. Releases are triggered by `gh release create` (via `./release.sh`).

## Karpathy Guidelines

Behavioral guidelines to reduce common LLM coding mistakes, derived from [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on LLM coding pitfalls.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

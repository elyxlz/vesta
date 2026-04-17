# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vesta is a personal AI assistant that runs as a persistent daemon in Docker, powered by the Claude Agent SDK. It monitors notifications, responds to messages, and handles tasks autonomously.

## Architecture

Client/server architecture. `vestad` daemon runs on the host (manages Docker containers, serves HTTP+WS API). `vesta` CLI and Tauri desktop app connect to vestad. On Linux, the CLI/app bootstraps vestad locally via systemd. On macOS/Windows, users connect to a remote vestad via `vesta connect`. Python agent runs inside the container.

- **Agent** (`agent/core/`): Async Python. Entry point `main.py`. Core loop in `core/loops.py` (message processing, notification monitoring). WebSocket server in `api.py`.
- **CLI** (`cli/`): standalone Rust crate — `vesta` client binary. Connects to vestad over HTTPS.
- **Server** (`vestad/`): standalone Rust crate — `vestad` daemon. Manages Docker containers, serves API. Contains `vestad/tests-integration/` as a workspace member for end-to-end tests.
- **Web App** (`apps/web/`): React + TypeScript SPA served by vestad at `/app` and embedded in the Tauri desktop wrapper. Components in `apps/web/src/components/`, providers in `apps/web/src/providers/`.
- **Desktop App** (`apps/desktop/`): Tauri wrapper around `@vesta/web`. Only `src-tauri/` + a thin `package.json` — no frontend code of its own.
- **Skills** (`agent/skills/`): Each skill directory has `SKILL.md` + scripts. No MCP servers.
- **Integration Tests** (`tests/`): Separate Rust crate with end-to-end tests (real vestad + client, requires Docker).

### Key Flows

**Agent creation**: CLI/app -> `POST /agents` on vestad -> allocates unique WS port, generates agent token, writes `~/.config/vesta/vestad/agents/{agent}.env` -> builds/pulls Docker image -> creates container with host networking and bind-mounted env file (`/run/vestad-env`) -> container starts, sources env, runs `uv run python -m core.main` -> initializes EventBus (SQLite), starts WS server on allocated port, starts message processor and notification monitor tasks.

**Message flow**: Client connects to vestad WS -> vestad proxies to agent container's WS port -> agent's `api.py` receives message, emits `UserEvent` to EventBus -> `message_processor` in `core/loops.py` picks it up, calls Claude Agent SDK (`client.query()`) -> streams response blocks (text, thinking, tool use) back through EventBus -> all WS subscribers receive events in real time. Supports message interruption: new message during processing triggers `client.interrupt()`.

**Notification flow**: External systems write JSON files to `~/agent/notifications/` inside the container. `monitor_loop` in `core/loops.py` watches with `watchfiles.awatch()`. Notifications marked `interrupt: true` immediately interrupt current processing and queue for the agent. Passive notifications batch and wait until agent is idle.

**Session persistence**: Agent persists a Claude SDK `session_id` to `~/agent/data/session_id`, allowing conversation resume across container restarts. All events stored in `~/agent/data/events.db` (SQLite with FTS5 for full-text search). The "dreamer" runs nightly at `NIGHTLY_MEMORY_HOUR`, curates memory, runs `/compact`, then restarts with a fresh session.

**Config injection**: vestad writes env vars to `agents/{agent}.env` on host, bind-mounted into container. Agent's `config.py` reads `VestaConfig` from env vars (`AGENT_NAME`, `AGENT_MODEL`, `WS_PORT`, `AGENT_TOKEN`, etc.). Custom prompts live in `~/agent/prompts/` (MEMORY.md, notification_suffix.md, nightly_dream.md, etc.).

**Auth**: vestad generates an API key at `~/.config/vesta/vestad/api-key` (clients use `Bearer` token or `?token=` query param). Each agent gets a unique `AGENT_TOKEN` for agent-to-vestad auth via `X-Agent-Token` header. TLS uses self-signed certs with fingerprint verification (no CA chain).

**Skills**: Each skill in `agent/skills/{name}/` has `SKILL.md` (YAML frontmatter with name/description) + CLI tools. Skills are registered as tools via Claude Agent SDK. `skills/index.json` is auto-generated and must be committed when skills change.

**Backup/restore**: `docker commit` creates image snapshots (`vesta-backup:{name}_{type}_{timestamp}`). Retention: 3 daily, 2 weekly, 1 monthly. Export/import via `docker save/load` for cross-machine transfer. All `~/agent/` state (events.db, session_id) survives backup/restore.

## Commands

> **Skills index**: When adding or modifying skills, run `uv run python agent/skills/generate-index.py` and commit `agent/skills/index.json`. CI fails if the index is stale.

### Agent (run from `agent/`)

```bash
uv run pytest tests/ --ignore=tests/test_e2e.py  # Unit tests
uv run pytest tests/test_notifications.py         # Single module
uv run pytest tests/ -k "test_batch"              # Single test by name
uv run pytest skills/tasks/cli/tests/             # Skill CLI tests
uv run ruff check                                 # Lint
uv run ty check                                   # Type check
```

### Rust (each crate is standalone)

```bash
# CLI (run from cli/)
cd cli && cargo build                      # Debug build
cd cli && cargo clippy                     # Lint
cd cli && cargo test                       # Unit tests

# Server (run from vestad/ — triggers `npm -w @vesta/web run build` via build.rs; set VESTAD_SKIP_APP_BUILD=1 to skip)
cd vestad && cargo build                   # Debug build
cd vestad && cargo clippy -p vestad        # Lint vestad only (not tests-integration)
cd vestad && cargo test -p vestad          # Unit tests
cd vestad && cargo test -p vesta-tests     # Integration tests (requires Docker)
```

### Frontend (run from `apps/`)

```bash
npm install                                # Installs workspace deps (one-time / after package.json changes)
npm -w @vesta/web run test                 # Web tests
npm -w @vesta/web run lint                 # Web lint
npm -w @vesta/web run check                # Web type check
npm -w @vesta/desktop run tauri -- <args>  # Run the Tauri CLI (dev, build, etc.)
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

### Frontend (apps/web/src/)
- **"Agent" terminology everywhere** — never "box". Types: `AgentInfo`, `AgentConnection`, `AgentActivityState`.
- **Tauri invoke() names must match Rust backend** — the invoke command strings are the contract, don't rename them.
- **Hook placement** — hooks used only by a single provider live in that provider's folder (e.g. `providers/VoiceProvider/use-voice-input.ts`). `hooks/` is reserved for shared hooks used across multiple components/providers.
- **Components in folders** — each component gets a folder with `index.tsx` and optionally `styles.ts`.

## CI

Runs on push to `master` and PRs. Checks: version sync across sources (`agent/pyproject.toml`, `vestad/Cargo.toml`, `cli/Cargo.toml`, `vestad/tests-integration/Cargo.toml`, `apps/desktop/src-tauri/Cargo.toml`, `apps/desktop/src-tauri/tauri.conf.json`, `apps/web/package.json`), ruff, ty, cargo clippy, pytest, `uv.lock` freshness. Releases are triggered by `gh release create` (via `./release.sh`).

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

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

It focuses on **how this system is built and the principles that govern it**. The concrete
working rules — build/test commands, per-language code conventions, CI, and the PR
process — live in **[`CONTRIBUTING.md`](./CONTRIBUTING.md)**, the authoritative standards doc every
agent follows. Read it before writing or shipping code.

## Project Overview

Vesta is a personal AI assistant that runs as a persistent daemon in Docker, powered by Claude Code. It monitors notifications, responds to messages, and handles tasks autonomously. The agent drives the `claude` CLI interactively inside tmux via an in-repo SDK (`agent/core/cc_sdk/`, see its README) that exposes the same client surface, because driving the CLI directly is simpler than wiring up the official Claude Agent SDK.

## Architecture

Client/server architecture. `vestad` daemon runs on the host (manages Docker containers, serves HTTP+WS API). `vesta` CLI and Tauri desktop app connect to vestad. On Linux, the CLI/app bootstraps vestad locally via systemd. On macOS/Windows, users connect to a remote vestad via `vesta connect`. Python agent runs inside the container.

- **Agent** (`agent/core/`): Async Python. Entry point `main.py`. Core loop in `core/loops.py` (message processing, notification monitoring). WebSocket server in `api.py`.
- **CLI** (`cli/`): standalone Rust crate — `vesta` client binary. Connects to vestad over HTTPS.
- **Server** (`vestad/`): standalone Rust crate — `vestad` daemon. Manages Docker containers, serves API. Contains `vestad/tests-integration/` as a workspace member for end-to-end tests.
- **Web App** (`apps/web/`): React + TypeScript SPA served by vestad at `/app` and embedded in both Tauri wrappers. Components in `apps/web/src/components/`, providers in `apps/web/src/providers/`.
- **Desktop App** (`apps/desktop/`): Tauri wrapper around `@vesta/web` for macOS/Windows/Linux. Only `src-tauri/` + a thin `package.json` — no frontend code of its own.
- **Mobile App** (`apps/mobile/`): Separate Tauri wrapper around `@vesta/web` for iOS/Android. Self-contained — independent Cargo crate (`vesta-mobile`), bundle id `com.vestarun.mobile`, no shared Rust code with desktop.
- **Skills** (`agent/skills/` + `agent/core/skills/`): Each skill directory has `SKILL.md` + scripts. `agent/core/skills/` holds built-in skills shipped with the agent (e.g. `app-chat`); `agent/skills/` holds the rest. No MCP servers.
- **Integration Tests** (`vestad/tests-integration/`): Rust crate (`vesta-tests`, workspace member of `vestad/`) with end-to-end tests (real vestad + client, requires Docker).

### Key Flows

**Agent creation**: CLI/app -> `POST /agents` on vestad -> allocates unique WS port, generates agent token, writes `~/.config/vesta/vestad/agents/{agent}.env` -> builds/pulls Docker image -> creates container with host networking and bind-mounted env file (`/run/vestad-env`) -> container starts, sources env, runs `uv run python -m core.main` -> initializes EventBus (SQLite), starts WS server on allocated port, starts message processor and notification monitor tasks.

**Message flow**: Client connects to vestad WS -> vestad proxies to agent container's WS port -> agent's `api.py` receives message, emits `UserEvent` to EventBus -> `message_processor` in `core/loops.py` picks it up, calls the cc_sdk client (`client.query()`, which pastes the prompt into the tmux `claude` session) -> streams response blocks (text, thinking, tool use), reconstructed from the session transcript and native hooks, back through EventBus -> all WS subscribers receive events in real time. Supports message interruption: new message during processing triggers `client.interrupt()`.

**Notification flow**: External systems write JSON files to `~/agent/notifications/` inside the container. `monitor_loop` in `core/loops.py` watches with `watchfiles.awatch()`. Notifications marked `interrupt: true` immediately interrupt current processing and queue for the agent. Passive notifications batch and wait until agent is idle.

**Session persistence**: Agent persists a Claude SDK `session_id` to `~/agent/data/session_id`, allowing conversation resume across container restarts. All events stored in `~/agent/data/events.db` (SQLite with FTS5 for full-text search). The events.db schema is versioned via `PRAGMA user_version`: `events.py` owns an ordered, version-gated `_MIGRATIONS` list applied at `EventBus` construction. Version 1 is the baseline (the current `CREATE ... IF NOT EXISTS` schema), so a fresh db and a pre-versioned db both converge to v1 with no data loss. Future schema changes add v2+ steps; never edit a released step. The "dreamer" runs nightly at `NIGHTLY_MEMORY_HOUR`, curates memory, then (via `mark_dreamer_complete`) compacts the conversation in place with `/compact` and restarts, resuming the compacted session so context stays continuous rather than resetting to a blank slate.

**Config injection**: vestad writes env vars to `agents/{agent}.env` on host, bind-mounted into container. Agent's `config.py` reads `VestaConfig` from env vars (`AGENT_NAME`, `AGENT_MODEL`, `WS_PORT`, `AGENT_TOKEN`, etc.). Custom prompts live in `~/agent/prompts/` (MEMORY.md, notification_suffix.md, nightly_dream.md, etc.).

**Auth**: vestad generates an API key at `~/.config/vesta/vestad/api-key` (clients use `Bearer` token or `?token=` query param). Each agent gets a unique `AGENT_TOKEN` for agent-to-vestad auth via `X-Agent-Token` header. TLS uses self-signed certs with fingerprint verification (no CA chain).

**Skills**: Each skill in `agent/skills/{name}/` or `agent/core/skills/{name}/` has `SKILL.md` (YAML frontmatter with name/description) + CLI tools. Skills are loaded natively by Claude Code (via `setting_sources` + the skill directories). `agent/skills/index.json` is auto-generated from both directories and must be committed when skills change (see [`CONTRIBUTING.md`](./CONTRIBUTING.md)).

**Backup/restore**: each backup is a `restic` snapshot in a single deduplicated, compressed, encrypted repository at `~/.config/vesta/vestad/restic-repo` (passphrase at `~/.config/vesta/vestad/restic-password`). A snapshot is `docker export <container>` streamed into `restic backup --stdin`, tagged `agent:<name>` + `type:<backup_type>`; restore is `restic dump | docker import` into a fresh container. Because restic deduplicates, retaining many snapshots of a multi-GB agent costs roughly one full copy plus per-run diffs (the old `docker export|import` model wrote an independent full image per backup, which filled the host disk). `restic` is located on PATH or extracted from a copy embedded into the vestad binary at build time (`build.rs` vendors it into `vestad/vendored/`, `src/restic_embed.rs` bakes it in, `src/restic.rs` extracts it — same mechanism as cloudflared). Retention (3 daily, 2 weekly, 1 monthly default) is computed in `compute_backups_to_delete` and applied via `restic forget --prune`. The separate `vestad backup export/import` file path (`.tar.gz` via `docker export`) is unchanged and used for cross-machine transfer. All `~/agent/` state (events.db, session_id) survives backup/restore.

## Contributing & standards

Build and test commands, per-language code conventions, CI behavior, the testing
strategy, and the PR process are documented in **[`CONTRIBUTING.md`](./CONTRIBUTING.md)**,
imported below so its standards are always loaded. Treat it as binding on every change.

@CONTRIBUTING.md

The Karpathy Guidelines (in [`CONTRIBUTING.md`](./CONTRIBUTING.md#karpathy-guidelines), imported above) and the Architecture Principles below govern *how* to apply those standards.

## Architecture Principles

Reconciled rubric for this system. Where canonical architecture advice fights Vesta's intentional design, the design wins (see resolved conflicts at the end of this section).

- **Deep modules, hidden decisions.** cc_sdk (`agent/core/cc_sdk/`) is the model: a small `ClaudeSDKClient` surface hiding all tmux paste, transcript tailing, hook bridging, and MCP stdio. Consume that surface, do not reach into `tmux.py`, `transcript.py`, or `_forward.py`.
- **Confine IO to edge modules.** Docker in `vestad/src/docker.rs`, restic in `restic.rs`, the claude driver in cc_sdk, SQLite + FTS5 in `agent/core/events.py`. No raw shellouts, HTTP calls, or SQL strings scattered into `loops.py`, `client.py`, or request handlers.
- **One owner per decision.** Notification format, the `agents/{name}.env` config contract, the cc_sdk interrupt protocol (double Escape, Stop-hook crediting): each lives in exactly one module. A constant or format appearing in two modules moves to its owner.
- **No shared crate between `cli` and `vestad`.** The JSON/WS wire contract, Tauri `invoke()` command strings, and the `X-Agent-Token` header are the only coupling. Duplicate small DTO shapes per crate rather than sharing a library.
- **Python stays functional.** Pure functions plus dataclasses/TypedDicts/pydantic models, no classes-with-methods. Pass `State` and `VestaConfig` as explicit keyword arguments (the functional stand-in for dependency injection).
- **Banned accessors.** No `getattr`, dict `.get()` fallback, or `hasattr` in Python. No `panic!`/`unwrap`/`expect` on fallible paths in `vestad/`/`cli/` (`expect` only where failure is impossible); return `Result`.
- **Named consts, descriptive names, minimal clone (Rust).** Follow `DOCKER_TIMEOUT_SECS`, `IMPORT_PIPELINE_MAX_ATTEMPTS`, `UPSTREAM_READY_POLL_MAX`.
- **Simple data across boundaries.** JSON events on the bus, env vars across the container boundary, serde DTOs across the HTTP API. No request objects, rows, or tmux internals crossing boundaries.
- **High cohesion, no grab-bags.** `helpers.py` and `lib/` stay narrowly scoped; a module whose name needs "and" gets split.
- **Design errors out of existence.** Prefer idempotent no-ops (`unlink(missing_ok=True)`, `mkdir(exist_ok=True)`, restic dedup) over special-case error branches.
- **Simplicity and surgical changes (Karpathy).** Solve only today's problem, no speculative flexibility for a single caller; match surrounding style, do not refactor adjacent working code, remove only the orphans your change created.
- **Comments explain why.** Reserve them for non-obvious mechanics (cc_sdk double-Escape, the watchfiles local-stop bridge, the circular dreamer window).

**Conflicts resolved (our design wins):** circuit breakers, per-dependency bulkhead pools, load-shed 429s, and golden-signal dashboards are skipped: Vesta is a single-tenant personal daemon where timeout + capped-retry + supervised-restart already bound blast radius. Formal ADR/C4 docs and SCA/SLSA supply-chain ceremony are replaced by CLAUDE.md plus CONTRIBUTING.md plus the memory feedback files as the in-repo decision record. Port/adapter interface objects are replaced by explicit-config-passing because Python is intentionally class-free.

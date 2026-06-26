# CLAUDE.md

This file is the single guide for Claude Code (claude.ai/code) when working in this repository:
**how the system is built and the principles that govern it** (Architecture, Architecture
Principles) and the **concrete working rules every agent follows** — build/test commands, code
conventions, the testing strategy, CI, the PR process, and the Karpathy Guidelines that govern
*how* you make changes. Read it before writing or shipping code; for install/setup see
[`README.md`](./README.md).

## Project Overview

Vesta is a personal AI assistant that runs as a persistent daemon in Docker, powered by Claude Code. It monitors notifications, responds to messages, and handles tasks autonomously. The agent drives Claude through the official **Claude Agent SDK** (`claude-agent-sdk`): `core/client.py` builds a `ClaudeAgentOptions`, opens a `ClaudeSDKClient`, and streams response blocks back from the SDK message stream and its native hooks.

> **cc_sdk is dormant — leave it alone.** `agent/core/cc_sdk/` is an in-repo SDK that drives the interactive `claude` CLI inside tmux and exposes the *same* `ClaudeSDKClient` surface. The agent used it for a stretch and it is retained deliberately as a drop-in alternative driver in case we need to return to CLI-driving (e.g. for behavior the headless SDK can't reach). It is **not** imported by `core/` anymore and is **not** on the running agent's path. Do not delete it, do not "tidy" it, and do not wire it back into `core/` without an explicit ask. Its transport tests (`tests/test_cc_sdk.py`, `tests/test_e2e_transport.py`, `tests/test_stop_race.py`) keep it healthy; keep them green.

## Architecture

Client/server architecture. `vestad` daemon runs on the host (manages Docker containers, serves HTTP+WS API). `vesta` CLI and Tauri desktop app connect to vestad. On Linux, the CLI/app bootstraps vestad locally via systemd. On macOS/Windows, users connect to a remote vestad via `vesta connect`. Python agent runs inside the container.

- **Agent** (`agent/core/`): Async Python. Entry point `main.py`. Core loop in `core/loops.py` (message processing, notification monitoring). WebSocket server in `api.py`.
- **CLI** (`cli/`): standalone Rust crate — `vesta` client binary. Connects to vestad over HTTPS.
- **Server** (`vestad/`): standalone Rust crate — `vestad` daemon. Manages Docker containers, serves API. Contains `vestad/tests-integration/` as a workspace member for end-to-end tests.
- **Web App** (`apps/web/`): React + TypeScript SPA served by vestad at `/app` and embedded in both Tauri wrappers. Components in `apps/web/src/components/`, providers in `apps/web/src/providers/`.
- **Desktop App** (`apps/desktop/`): Tauri wrapper around `@vesta/web` for macOS/Windows/Linux. Only `src-tauri/` + a thin `package.json` — no frontend code of its own.
- **Mobile App** (`apps/mobile/`): Separate Tauri wrapper around `@vesta/web` for iOS/Android. Self-contained — independent Cargo crate (`vesta-mobile`), bundle id `com.vestarun.mobile`, no shared Rust code with desktop.
- **Skills** (`agent/skills/` + `agent/core/skills/`): Each skill directory has `SKILL.md` + scripts. `agent/core/skills/` holds built-in skills shipped with the agent (e.g. `app-chat`); `agent/skills/` holds the rest. Skills are plain directories, not MCP servers — the only MCP server is the agent's own native tool registry (`core/tools.py`), exposed to Claude in-process via the Claude Agent SDK's `create_sdk_mcp_server`.
- **Integration Tests** (`vestad/tests-integration/`): Rust crate (`vesta-tests`, workspace member of `vestad/`) with end-to-end tests (real vestad + client, requires Docker).

### Key Flows

**Agent creation**: CLI/app -> `POST /agents` on vestad -> allocates unique WS port, generates agent token, writes `~/.config/vesta/vestad/agents/{agent}.env` -> builds/pulls Docker image -> creates container with host networking and bind-mounted env file (`/run/vestad-env`) -> container starts, sources env, runs `uv run python -m core.main` -> initializes EventBus (SQLite), starts WS server on allocated port, starts message processor and notification monitor tasks.

**Message flow**: Client connects to vestad WS -> vestad proxies to agent container's WS port -> agent's `api.py` receives message, emits `UserEvent` to EventBus -> `message_processor` in `core/loops.py` picks it up, calls the Claude Agent SDK client (`client.query()`) -> streams response blocks (text, thinking, tool use) from the SDK message stream and native hooks, back through EventBus -> all WS subscribers receive events in real time. Supports message interruption: new message during processing triggers `client.interrupt()`.

**Notification flow**: External systems write JSON files to `~/agent/notifications/` inside the container. `monitor_loop` in `core/loops.py` watches with `watchfiles.awatch()`. Notifications marked `interrupt: true` immediately interrupt current processing and queue for the agent. Passive notifications batch and wait until agent is idle.

**Session persistence**: Cross-restart state lives in `~/agent/data/state.json` — a single, atomically written `PersistedState` blob owned by `state_store.py` holding the Claude SDK `session_id` (for conversation resume), boot markers, `migrations.applied`, and the last dreamer run. Legacy per-marker files (the old `session_id` file, `first_start_done`, `last_dreamer_run`, etc.) are imported into it and removed on first boot. All events are stored in `~/agent/data/events.db` (SQLite with FTS5 for full-text search). The events.db schema is versioned via `PRAGMA user_version`: `events.py` owns an ordered, version-gated `_MIGRATIONS` list applied at `EventBus` construction. Version 1 is the baseline (the current `CREATE ... IF NOT EXISTS` schema), so a fresh db and a pre-versioned db both converge to v1 with no data loss. Future schema changes add v2+ steps; never edit a released step. The "dreamer" runs nightly at `NIGHTLY_MEMORY_HOUR`, curates memory, then (via `mark_dreamer_complete`) compacts the conversation in place with `/compact` and restarts, resuming the compacted session so context stays continuous rather than resetting to a blank slate.

**Migrations** (agent-state, distinct from the events.db schema migrations above): `migrations.py` runs prompt-based migrations — markdown files under `agent/core/migrations/`. On boot each unapplied migration is dropped as a passive notification (source `core`, type `migration`); the prompt's final step calls the `mark_migration_applied(name)` tool, which records it in `state.json`. If the agent never marks it (rate limit, crash, hallucinated success) it re-runs next boot, so migration prompts must be idempotent. Fresh agents pre-mark every shipping migration without running it — migrations exist only to converge legacy state on update.

**Config (two bricks, one home each)**: agent configuration is split by kind so each value has a single owner. **Identity** (`WS_PORT`, `AGENT_TOKEN`, `AGENT_NAME`, `TZ`, tunnel): vestad writes it to `agents/{agent}.env` on host at creation, bind-mounted read-only into the container; the agent never writes it. **Config** (the agent's instance): a single nested store at `~/agent/data/config.json`, modeled by `config.py`'s `VestaConfig`. It holds the active `provider` (a pydantic discriminated union, `ClaudeConfig | OpenRouterConfig`, carrying that provider's model + context + thinking + credential) plus provider-independent prefs (`agent_personality`, `timezone`, `seed_context`). The **provider** is its own resource: set/switched via `PUT /provider` (sign in), tweaked via `PATCH /provider` (model/context/thinking), and cleared via `DELETE /provider` (sign out); `PUT /config` is prefs-only and rejects a `provider` key. The OpenRouter key lives nested in `provider` (redacted `SecretStr` on the wire); the Claude OAuth blob lives in `.credentials.json`, which the `claude` CLI reads and refreshes directly, so it is loaded into the model at boot but never persisted to the store (see the LLM provider section). `VestaConfig` layers pydantic-settings sources, highest first: init args, the config store (so a write overrides anything stale), env (identity + operational scalars only; the provider lives in the store, not env), then the model's own field defaults. A one-shot boot migration relocates any legacy flat keys (`agent_model`/`agent_provider`/`openrouter_key`/...) into the nested `provider`; that is the only place flat↔nested mapping lives. New-agent defaults + the per-provider catalog (model lists, context presets, thinking support) come from `agent/core/manifest.json`, **generated from the provider models** by `agent/generate-manifest.py` (CI checks it's fresh) and served by vestad at `GET /manifest` — the model is the one source, the manifest its projection for the non-Python layers. Custom prompts live in `~/agent/prompts/` (MEMORY.md, notification_suffix.md, nightly_dream.md, etc.).

**LLM provider**: Each agent talks to either Claude (OAuth, the default) or OpenRouter (API key), modeled as `config.provider` (the `ClaudeConfig | OpenRouterConfig` discriminated union). The union makes illegal states unrepresentable: openrouter structurally requires a key, claude carries the thinking knob + its OAuth blob. `provider.py` owns this upstream relationship: the provider + OpenRouter key live nested in the config store, while the Claude OAuth blob lives in `.credentials.json` (the `claude` CLI reads and refreshes it), loaded into the model at boot. `client.py` injects the OpenRouter key into the SDK subprocess env, so nothing is shell-sourced at container start. The provider is set via `PUT /provider`, changed via `PATCH /provider`, and cleared via `DELETE /provider` — write-only, the caller restarts the agent once afterwards to apply (so provisioning is a few writes + a single restart, never a per-write restart race); `set_claude`/`set_openrouter` merge onto the existing provider so a re-auth or a model-only patch preserves the rest. Auth state is the single source of truth on disk, re-derived from `.credentials.json` + the config store on every boot, with a terminal runtime 401/402 flipping it in-memory only (no persisted flag). OpenRouter traffic is proxied and cached by `openrouter_cache.py`. This is distinct from the agent's own HTTP API auth below.

**Auth**: vestad generates an API key at `~/.config/vesta/vestad/api-key` (clients use `Bearer` token or `?token=` query param). Each agent gets a unique `AGENT_TOKEN` for agent-to-vestad auth via `X-Agent-Token` header. TLS uses self-signed certs with fingerprint verification (no CA chain).

**Constitution**: Each agent has a user-authored `constitution.md` (host `agents/{name}.constitution.md`) bind-mounted **read-only** at `/root/agent/constitution.md`, in a separate mount from the core-code mount (`/root/agent/core`) so agent self-updates never touch it. The agent reads its constitution but cannot edit it — the user's immutable rules.

**Skills**: Each skill in `agent/skills/{name}/` or `agent/core/skills/{name}/` has `SKILL.md` (YAML frontmatter with name/description) + CLI tools. Skills are loaded natively by Claude Code (via `setting_sources` + the skill directories). `agent/skills/index.json` is auto-generated from both directories and must be committed when skills change (see [Adding a skill](#adding-a-skill)). The bracketed `[Fill in...]` placeholders in a skill's `SKILL.md` are intentional personalization scaffolding the agent fills in per user over time; leave them intact, they are not dead space.

**Backup/restore**: each backup is a `restic` snapshot in a single deduplicated, compressed, encrypted repository at `~/.config/vesta/vestad/restic-repo` (passphrase at `~/.config/vesta/vestad/restic-password`). A snapshot is `docker export <container>` streamed into `restic backup --stdin`, tagged `agent:<name>` + `type:<backup_type>`; restore is `restic dump | docker import` into a fresh container. Because restic deduplicates, retaining many snapshots of a multi-GB agent costs roughly one full copy plus per-run diffs (the old `docker export|import` model wrote an independent full image per backup, which filled the host disk). `restic` is located on PATH or extracted from a copy embedded into the vestad binary at build time (`build.rs` vendors it into `vestad/vendored/`, `src/restic_embed.rs` bakes it in, `src/restic.rs` extracts it — same mechanism as cloudflared). Retention (3 daily, 2 weekly, 1 monthly default) is computed in `compute_backups_to_delete` and applied via `restic forget --prune`. The separate `vestad backup export/import` file path (`.tar.gz` via `docker export`) is unchanged and used for cross-machine transfer. All `~/agent/` state (events.db, state.json) survives backup/restore.

## Architecture Principles

Reconciled rubric for this system. Where canonical architecture advice fights Vesta's intentional design, the design wins (see resolved conflicts at the end of this section). The Karpathy Guidelines and the working rules below govern *how* to apply these principles.

- **Deep modules, hidden decisions.** The Claude Agent SDK is the model: a small `ClaudeSDKClient` surface hiding the whole headless control protocol. Consume that surface; keep the SDK seam in `core/client.py` + `core/sdk_parsing.py`, do not scatter SDK internals across `loops.py`. (The dormant `cc_sdk` exemplifies the same principle for the CLI-driving path — see the Project Overview note.)
- **Confine IO to edge modules.** Docker in `vestad/src/docker.rs`, restic in `restic.rs`, the claude driver behind the `claude_agent_sdk` client surface, SQLite + FTS5 in `agent/core/events.py`. No raw shellouts, HTTP calls, or SQL strings scattered into `loops.py`, `client.py`, or request handlers.
- **One owner per decision.** Notification format, the `agents/{name}.env` config contract, the SDK option/hook mapping (`core/client.py` builds `ClaudeAgentOptions`, `core/sdk_parsing.py` owns the hook wiring): each lives in exactly one module. A constant or format appearing in two modules moves to its owner.
- **No shared crate between `cli` and `vestad`.** The JSON/WS wire contract, Tauri `invoke()` command strings, and the `X-Agent-Token` header are the only coupling. Duplicate small DTO shapes per crate rather than sharing a library.
- **Python stays functional.** Pure functions plus dataclasses/TypedDicts/pydantic models, no classes-with-methods. Pass `State` and `VestaConfig` as explicit keyword arguments (the functional stand-in for dependency injection).
- **Banned accessors.** No `getattr`, dict `.get()` fallback, or `hasattr` in Python. No `panic!`/`unwrap`/`expect` on fallible paths in `vestad/`/`cli/` (`expect` only where failure is impossible); return `Result`.
- **Named consts, descriptive names, minimal clone (Rust).** Follow `DOCKER_TIMEOUT_SECS`, `IMPORT_PIPELINE_MAX_ATTEMPTS`, `UPSTREAM_READY_POLL_MAX`.
- **Simple data across boundaries.** JSON events on the bus, env vars across the container boundary, serde DTOs across the HTTP API. No request objects, rows, or tmux internals crossing boundaries.
- **High cohesion, no grab-bags.** `helpers.py` and `lib/` stay narrowly scoped; a module whose name needs "and" gets split.
- **Design errors out of existence.** Prefer idempotent no-ops (`unlink(missing_ok=True)`, `mkdir(exist_ok=True)`, restic dedup) over special-case error branches.
- **Surgical by default; restructure when the structure forces a workaround.** Default to the smallest change that solves today's problem: match surrounding style, don't refactor working code for taste, remove only the orphans you create, no speculative flexibility for a single caller. But "surgical" is never a license to graft a workaround onto a structure that can't hold it — when a local fix would force duplication, a non-scalable interface, or new coupling, fix the structure instead; that change still traces to the request. Working around bad structure is the *expensive* choice: it piles up half-right interfaces, bugs that span the seams, and coupling the next change inherits. The bar for touching more code is "the current shape forces a worse change," not taste. When you are genuinely torn between the surgical patch and a more rounded fix that touches more code but pays off long-term, do not pick silently — lay both out (blast radius now vs. long-term gain, what each leaves behind) and let the user choose.
- **One fix per root cause, not belt-and-suspenders.** Once you've found the actual cause, fix it at that one layer. Do not stack a redundant defensive guard elsewhere "just in case" — overlapping fixes accumulate, and the next debugger can't tell which one matters or that the real cause was ever addressed, so each layer masks the next. If a second layer seems necessary, that means you haven't found the root cause yet — keep looking. Prefer deleting a now-redundant guard over adding another.
- **Comments explain why.** Reserve them for non-obvious mechanics (cc_sdk double-Escape, the watchfiles local-stop bridge, the circular dreamer window).
- **Mark transitional code for removal.** Code that exists only to converge old fleet state (back-compat shims, fallback config sources, one-shot renames) carries a grep-able marker so it can be found and deleted once justified: `LEGACY(remove-when: <concrete, checkable condition>): <what and why>`. The condition must be evaluable later (a version, a date, or a fleet state), never "someday". Enumerate with `rg 'LEGACY\('`; when the condition holds, delete the marked code and its tests in one PR. Prompt-based migrations under `agent/core/migrations/` are inherently legacy and don't need the marker; everything else does.

**Conflicts resolved (our design wins):** circuit breakers, per-dependency bulkhead pools, load-shed 429s, and golden-signal dashboards are skipped: Vesta is a single-tenant personal daemon where timeout + capped-retry + supervised-restart already bound blast radius. Formal ADR/C4 docs and SCA/SLSA supply-chain ceremony are replaced by this CLAUDE.md plus the memory feedback files as the in-repo decision record. Port/adapter interface objects are replaced by explicit-config-passing because Python is intentionally class-free.

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

**But surgical is not a license to work around bad structure.** "Touch only what you must" governs *taste-driven* changes — don't refactor working code because you'd write it differently. It does NOT mean bolt a workaround onto a shape that can't hold the change. If a local fix would force duplication, a non-scalable interface, or new coupling, the structural fix *is* what the request requires — make it, even though it touches more code. The workaround is the costlier path: it accumulates half-right interfaces, cross-seam bugs, and coupling the next change inherits.

When you are genuinely uncertain which is right — the small surgical patch, or a more rounded fix that touches more code but brings long-term gains — do not choose silently. Present both options with their tradeoffs (blast radius and risk now vs. what the surgical patch leaves for later) and let the user decide.

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

## Project layout

Vesta is a client/server system: the `vestad` daemon runs on the host, the `vesta` CLI and
desktop/mobile apps connect to it, and a Python agent runs inside a Docker container. Each
crate/app is standalone — see [Architecture](#architecture).

```
agent/        # async Python agent (uv) — entry point core/main.py
cli/          # vesta client (standalone Rust crate)
vestad/       # vestad daemon (standalone Rust crate) + tests-integration/
apps/web/     # React + TypeScript SPA (@vesta/web)
apps/desktop/ # Tauri wrapper (macOS/Windows/Linux)
apps/mobile/  # Tauri wrapper (iOS/Android)
agent/skills/ + agent/core/skills/  # skills (SKILL.md + scripts)
```

## Commands

> **Skills index**: When adding or modifying skills, run `uv run python agent/skills/generate-index.py` and commit `agent/skills/index.json`. CI fails if the index is stale.

### check.sh (single entry point, run from repo root)

CI runs these exact subcommands, so passing locally means passing CI:

```bash
./check.sh agent          # ruff check + ruff format --check + ty check + pytest (incl. cc_sdk transport tests; needs tmux)
./check.sh cli            # cargo clippy -D warnings + cargo test
./check.sh vestad         # cargo clippy -p vestad -D warnings + cargo test -p vestad
./check.sh vestad-docker  # vestad #[ignore] Docker tests (needs Docker + agent image)
./check.sh web            # eslint + prettier --check + tsc + vitest
./check.sh integration    # vestad integration tests (needs Docker)
./check.sh live           # live agent e2e (Docker + ~/.claude/.credentials.json; real Claude)
./check.sh all            # agent + cli + vestad + web
```

### Finer-grained commands

```bash
# Agent (run from agent/)
uv run pytest tests/                                # All agent tests
uv run pytest tests/test_notifications.py           # Single module
uv run pytest tests/ -k "test_batch"                # Single test by name
uv run pytest tests/test_e2e_transport.py           # cc_sdk e2e (fake claude TUI in real tmux; requires tmux)
uv run pytest skills/tasks/cli/tests/               # Skill CLI tests

# Rust (each crate is standalone)
cd cli && cargo build                      # Debug build
# vestad builds trigger `npm -w @vesta/web run build` via build.rs; set VESTAD_SKIP_APP_BUILD=1 to skip
cd vestad && cargo build                   # Debug build
cd vestad && cargo test -p vesta-tests --test server  # Single integration suite

# Frontend (run from apps/)
npm install                                # Installs workspace deps (one-time / after package.json changes)
npm -w @vesta/desktop run tauri -- <args>  # Run the desktop Tauri CLI (dev, build, etc.)
npm -w @vesta/mobile run ios:build         # Build signed iOS .ipa (also ios:dev, android:build, android:dev)
```

On iOS, install the resulting .ipa to a paired device without Xcode GUI: `xcrun devicectl device install app --device <udid> apps/mobile/src-tauri/gen/apple/build/arm64/Vesta.ipa`. Never press ▶ in the generated Xcode project — the "Build Rust Code" phase depends on `npm` on PATH, and Xcode launched from Finder doesn't inherit nvm.

### Releasing

```bash
./release.sh         # Patch release (0.1.0 -> 0.1.1)
./release.sh minor   # Minor release (0.1.0 -> 0.2.0)
./release.sh major   # Major release (0.1.0 -> 1.0.0)
```

Run locally on master. Bumps versions, updates lockfiles, commits, pushes, and creates the GitHub release. CI then builds artifacts and publishes.

**Do NOT bump versions in PRs** — `release.sh` handles version bumps automatically at release time.

## Code conventions

### Python (agent/)
- **Always `uv run`**, never bare `python`
- **`getattr`, `.get()` (dict), `hasattr` are banned** — use direct access, `in` checks, or try/except
- **No silent exception swallowing** — prefer explicit checks (`if path.exists()`) or log the error
- Minimize comments — only for truly complex logic
- Line length: 144 (ruff)

### Async Python (agent/)
- **No blocking calls in coroutines** — no `time.sleep`, `requests`, sync `subprocess`/`open`/`input`, or inline CPU heavy work inside an `async def`. Use `asyncio.sleep`, an async client, `create_subprocess_exec`, or `asyncio.to_thread`/`run_in_executor`.
- **Own your tasks** — keep a strong reference to every `create_task` (e.g. a set with `add_done_callback(set.discard)`) and consume its exceptions (await, inspect `task.exception()`, or use a `TaskGroup`). Never fire `create_task` as a bare statement.
- **Respect cancellation** — in `except asyncio.CancelledError` do cleanup then re-raise. Do not put unshielded `await` in `finally` cleanup. From a non loop thread use only `call_soon_threadsafe`/`run_coroutine_threadsafe`.
- **No mutable default args** — default to `None`, build inside the body. Compare to `None` with `is`/`is not`.
- Log with `%`-style placeholders (`logger.info("x=%s", value)`), not pre-formatted f-strings.

### Rust (cli/, vestad/)
- **No panics in library/server code** — return `Result`, never `panic!()` or `.unwrap()` on fallible operations. `.expect()` only where failure is truly impossible.
- **Named constants for magic numbers** — timeouts, buffer sizes, port numbers, retry counts go in `const` at the top of the file.
- **Descriptive variable names** — no single-letter vars (`n`, `t`, `c`). Use `name`, `tag`, `client`.
- **Minimize `.clone()`** — move values into closures when possible, only clone when the value is genuinely needed afterward.
- **Extract repeated patterns** — if 3+ lines appear twice, extract a helper function.
- **Error types**: public errors implement `std::error::Error` and are `Send + Sync + 'static`; never `()` or bare `String`. `Display` messages are lowercase, no trailing punctuation, source chained via `Error::source`.
- **Private fields by default**, access via methods; public fields only for plain data structs with no invariants. Keep derivable bounds on the `derive`/`impl`, not the type definition.
- **Eagerly derive** `Debug` (non empty) plus `Clone`/`Copy`/`PartialEq`/`Default` where correct; `Box` oversized enum variants.
- **Typed args** over unlabeled `bool`/`Option` flags; group args into a struct/builder past ~5 to 7. No lossy `as` casts for fallible conversions (use `From`/`TryFrom`); avoid catch-all match arms when exhaustive handling is feasible. Every `unsafe` block carries a `// SAFETY:` justification.

### Frontend (apps/web/src/)
- **"Agent" terminology everywhere** — never "box". Types: `AgentInfo`, `AgentConnection`, `AgentActivityState`.
- **Tauri invoke() names must match Rust backend** — the invoke command strings are the contract, don't rename them.
- **Hook placement** — hooks used only by a single provider live in that provider's folder (e.g. `providers/VoiceProvider/use-voice-input.ts`). `hooks/` is reserved for shared hooks used across multiple components/providers.
- **Components in folders** — each component gets a folder with `index.tsx` and optionally `styles.ts`.
- **No dividers inside cards** — never separate sections within a card using a divider/separator line (`border-t`/`border-b`, `<Separator>`, `<hr>`). Group sections with spacing (`gap`, padding) instead. This is a hard preference, not case-by-case.
- **Rules of Hooks**: call Hooks only at the top level of a component or custom Hook, only from React contexts. Keep render pure (no side effects, no mutating props/state/context).
- **Effects are a last resort**: compute derived data during render (or `useMemo`), put interaction logic in event handlers. Every Effect has complete deps (`react-hooks/exhaustive-deps`), one concern, and cleanup for any subscription, timer, listener, or fetch (ignore/abort flag).
- **Stable list keys** from data identity, never array index for reorderable lists; reset state with a `key` prop, not an Effect.
- **Strict TS**: `strict: true`; no `any` (use `unknown` and narrow), avoid `as`/`!` assertions, annotate object literals rather than asserting, strict equality except `== null`, named exports.

## Adding a skill

Skills are how Vesta reaches the world — each is a directory the agent (and Claude Code)
loads natively. There are two locations:

- `agent/skills/{name}/` — most skills.
- `agent/core/skills/{name}/` — built-in skills shipped with the agent (e.g. `app-chat`).

Every skill has a `SKILL.md` with YAML frontmatter (`name` + `description`):

```markdown
---
name: tasks
description: Tasks, to-dos, reminders, time-based alerts; create and manage. Requires daemon.
---

# Tasks + Reminders - CLI: tasks

<usage, commands, examples — the body the agent reads when the skill activates>
```

The **`description` is discovery text**: it's what the agent sees when deciding whether to
use the skill, so write it as *when to use / triggers*, not just a label. Keep it tight.

If the skill ships a CLI, put it in a `cli/` subdirectory as its **own standalone `uv`
project** (`cli/pyproject.toml` + `cli/uv.lock`) with tests under `cli/tests/`:

```
agent/skills/tasks/
├── SKILL.md
└── cli/
    ├── pyproject.toml
    ├── uv.lock
    └── tests/        # test_e2e.py, test_fields.py, ...
```

Run a skill's CLI tests with `uv run pytest skills/{name}/cli/tests/` (from `agent/`).

**Always regenerate the index** after adding or editing a skill, and commit it:

```bash
uv run python agent/skills/generate-index.py   # rebuilds agent/skills/index.json from every SKILL.md
```

`index.json` is auto-generated from the `name` + `description` frontmatter across both skill
directories. **CI fails if it is stale**, so commit it in the same PR.

## Testing strategy

- **`check.sh` is the only entry point.** Every suite (`agent`, `cli`, `vestad`, `vestad-docker`, `web`, `integration`, `live`) runs through it; CI calls the same subcommands so local equals CI. Do not add a CI step that bypasses it.
- **Keep the pyramid.** Fast in-process pytest and Rust `--bins` unit tests are the default loop; Docker-gated suites are the middle tier; `live` (real Claude) is the tiny apex run only on release. Do not push Docker- or Claude-dependent assertions into the fast tiers.
- **Prefer the high-fidelity fake over mocks.** Drive cc_sdk tests through `tests/fake_claude.py` (a real fake claude TUI in real tmux) and exercise the real EventBus/SQLite. Reserve patching for true edges (file times, credentials presence). Keep `fake_claude.py` faithful to the real claude protocol; the e2e transport tests hold it to that contract.
- **Hermetic and deterministic.** Each test builds its own tmpdir db / notifications dir and passes in isolation and any order. No shared `events.db`, no wall-clock ordering, no dependence on a running agent.
- **Never `sleep()` to await a condition.** Poll with a timeout (`tests/wait_util.py`) or drive the event-driven loops via their `asyncio.Event` signals.
- **Test observable behavior through public surfaces.** Emit a `UserEvent` and assert the resulting event stream / persisted state, not which internal function fired. Behavior names read as sentences.
- **Table-driven tests are fine; keep logic out of test bodies.** Parametrize repetitive cases (`@pytest.mark.parametrize`, Rust table tests) rather than copy-paste, but no computed expected values or conditionals in the body itself. The sanctioned exception is hypothesis property tests (`test_property.py`).
- **Beyonce rule, mapped to suites.** Crash recovery / resume -> `test_crash_recovery.py`; interrupts / compaction deferral -> `test_interrupts.py`; notification batching -> `test_notifications.py`; backup/restore and ports -> vestad tests; skill-index freshness -> CI. If you do not want it to break, it has a test.
- **Coverage is a diagnostic, never a gate.** Do not add a coverage threshold. A line is tested only when a behavioral assertion exercises it.
- **Red is stop-the-line.** A failing main branch or `check.sh` suite is reverted or fixed forward immediately. When a flaky test surfaces (e.g. the integration suite needs a retry), quarantine or fix it, do not blanket-rerun.
- **Reliability is tested, not assumed.** Every finite timeout, capped retry (`retry_import_pipeline`), single-shot session-resume guard, cancellation path, and `finally`-block resource release has behavioral coverage.

**Tests ship with logic changes** in the same PR; no permanently skipped or panic-only tests, assert concrete values.

## CI

One workflow (`ci.yml`) runs on push to `master`, PRs, and releases; jobs are path-filtered on PRs. The check/test jobs call `./check.sh` subcommands, so CI and local checks are identical by construction. Checks: version sync across sources (`agent/pyproject.toml`, `vestad/Cargo.toml`, `cli/Cargo.toml`, `vestad/tests-integration/Cargo.toml`, `apps/desktop/src-tauri/Cargo.toml`, `apps/desktop/src-tauri/tauri.conf.json`, `apps/desktop/package.json`, `apps/mobile/src-tauri/Cargo.toml`, `apps/mobile/src-tauri/tauri.conf.json`, `apps/mobile/package.json`, `apps/web/package.json`), ruff, ty, cargo clippy, pytest (incl. cc_sdk e2e transport tests under tmux), `uv.lock` freshness. The single required branch-protection check is `merge-gate-ci`.

Docker-based jobs (integration tests, vestad Docker unit tests, live tests) build the agent image **from the checkout** (GHA layer cache) and run with `VESTAD_AGENT_IMAGE=vesta:local`, so PRs are validated against their own agent code and Dockerfile, never the previously released image.

A live agent e2e job (`test-live`) runs a real agent against real Claude using the `CLAUDE_CREDENTIALS` secret **only on the release event** (not PRs — it is slow and spends API tokens) and gates the release: a failure blocks publishing artifacts and the `:latest` image. Releases are triggered by `gh release create` (via `./release.sh`). Mobile (iOS/Android) builds from `apps/mobile`, desktop builds from `apps/desktop` — they share no Rust code.

## Pull requests

- **One concern per PR.** Isolate renames/moves and dependency bumps (manifest plus lockfile together) from logic changes. Add new dependencies conservatively and justify any new cross-module edge.
- **Conventional Commits** subjects (`feat`, `fix`, `refactor`, etc.), imperative mood, no trailing period, no closing keywords or @mentions in commit messages (those go in the PR body).
- **Tests ship with logic changes** in the same PR.
- **Do NOT bump versions in PRs** — `release.sh` handles version bumps at release time.
- **Update the skills index** when adding or modifying skills: run `uv run python agent/skills/generate-index.py` and commit `agent/skills/index.json` (CI fails if it is stale).
- Run the relevant `./check.sh` subcommands before pushing. The single required branch-protection check is `merge-gate-ci`.

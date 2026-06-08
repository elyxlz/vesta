# Contributing to Vesta

Thanks for contributing! This is the authoritative standards doc for developers and AI
coding agents: build/test commands, code conventions, the testing strategy, CI behavior,
and the PR process. For how the system is built and the design principles that govern it,
see **[`CLAUDE.md`](./CLAUDE.md)** (architecture + Karpathy Guidelines + Architecture
Principles). For install/setup, see [`README.md`](./README.md).

> **Two files, one source of truth.** `CLAUDE.md` is loaded automatically by Claude Code
> and covers architecture and principles. `CONTRIBUTING.md` (this file) covers the concrete
> contributor workflow. Neither duplicates the other — they cross-link.

## Project layout

Vesta is a client/server system: the `vestad` daemon runs on the host, the `vesta` CLI and
desktop/mobile apps connect to it, and a Python agent runs inside a Docker container. Each
crate/app is standalone — see [`CLAUDE.md` → Architecture](./CLAUDE.md#architecture).

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
- **DAMP over DRY; no logic in example tests.** No computed expected values or conditionals. The sanctioned exception is hypothesis property tests (`test_property.py`).
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

For architecture and the design principles behind these standards, see [`CLAUDE.md`](./CLAUDE.md).

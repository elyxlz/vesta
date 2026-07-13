# CLAUDE.md

The single guide for Claude Code when working in this repository: how the system is built, the principles that govern it, and the working rules every agent follows (commands, conventions, testing, CI, PRs, and the Karpathy Guidelines that govern *how* you make changes). Read it before writing or shipping code; install/setup lives in [`README.md`](./README.md).

## Project Overview

Vesta is an AI guardian angel that runs as a persistent daemon in Docker, powered by Claude Code. Vesta monitors notifications, responds to messages, and handles tasks autonomously. The agent drives Claude through the official **Claude Agent SDK** (`claude-agent-sdk`): `core/client.py` builds a `ClaudeAgentOptions`, opens a `ClaudeSDKClient`, and streams response blocks back from the SDK message stream and its native hooks.

> **cc_sdk is dormant, leave it alone.** `agent/core/cc_sdk/` is an in-repo SDK that drives the interactive `claude` CLI inside tmux and exposes the *same* `ClaudeSDKClient` surface. It is retained deliberately as a drop-in alternative driver in case CLI-driving is ever needed again (e.g. behavior the headless SDK can't reach); it is not imported by `core/` and not on the running agent's path. Do not delete it, tidy it, or wire it back into `core/` without an explicit ask. Its transport tests (`tests/test_cc_sdk.py`, `tests/test_e2e_transport.py`, `tests/test_stop_race.py`) keep it healthy; keep them green.

## Architecture

Client/server: the `vestad` daemon runs on the host (manages Docker containers, serves the HTTP+WS API); the `vesta` CLI and the desktop app connect to it. On Linux the CLI/app bootstraps vestad locally via systemd; on macOS/Windows users connect to a remote vestad via `vesta connect`. The Python agent runs inside the container.

- **Agent** (`agent/core/`): async Python. Entry point `main.py`, core loop in `core/loops.py` (message processing, notification monitoring), WebSocket server in `api.py`.
- **CLI** (`cli/`): standalone Rust crate, the `vesta` client binary. Connects to vestad over HTTPS.
- **Server** (`vestad/`): standalone Rust crate, the `vestad` daemon. Manages Docker containers, serves the API. Contains `vestad/tests-integration/` (crate `vesta-tests`, a workspace member) with end-to-end tests against a real vestad + client (requires Docker).
- **Web App** (`apps/web/`): React + TypeScript SPA served by vestad at `/app` and embedded in the desktop app. Components in `apps/web/src/components/`, providers in `apps/web/src/providers/`. Runtime detection and every native capability live in one bridge (`apps/web/src/lib/native/`) with `electron` and `browser` implementations; phones use the vestad-served SPA in a browser (a React Native app may come later).
- **Desktop App** (`apps/desktop/`): Electron wrapper around `@vesta/web` for macOS/Windows/Linux; a TypeScript main process (`src/`: window chrome, preload bridge, connection store, PKCE loopback, exact-version updater), no frontend code of its own.
- **Skills** (`agent/skills/` + `agent/core/skills/`): each skill directory has `SKILL.md` + scripts. `agent/core/skills/` holds built-ins shipped with the agent (e.g. `app-chat`, `upstream-sync`); `agent/skills/` holds the rest. On a box, skills are installed via the sparse-checkout cone of the local workspace checkout (`skills-install` = `git sparse-checkout add`, `skills-remove` drops the cone entry; instant and offline, content comes from local branch history). Skills are plain directories, not MCP servers; the only MCP server is the agent's own native tool registry (`core/tools.py`), exposed in-process via the SDK's `create_sdk_mcp_server`.

### Key Flows

**Agent creation**: CLI/app -> `POST /agents` on vestad -> allocates a unique WS port, generates an agent token, writes `~/.config/vesta/vestad/agents/{agent}.env` -> builds/pulls the Docker image -> creates the container with host networking and the env file bind-mounted (`/run/vestad-env`) -> the container sources env and runs `uv run python -m core.main` -> initializes the EventBus (SQLite), starts the WS server on the allocated port, starts the message processor and notification monitor tasks.

**Agent lifecycle (vestad owns it)**: containers run with Docker's `on-failure:5` restart policy: Docker recovers a genuine crash but never auto-starts a stale container on daemon/host boot, so vestad owns the boot sequence. On startup `reconcile_containers` (`docker.rs`) runs in order: ensure env files -> rebuild any container whose config (entrypoint/mounts) drifted (snapshot + recreate) -> migrate every container's policy to `on-failure` in place (`docker update`, no snapshot; a policy change is never a rebuild trigger) -> start each agent whose desired-run state is running, and stop any user-stopped one that's up. Rebuilds finish before the start step, so an agent needing a rebuild is never reachable on its pre-update container. On its own shutdown vestad stops all agents (`stop_all_agents`), so a `vestad update`/restart hands off clean. Desired-run state is `user_desired` (`running`|`stopped`, default running) per agent in vestad's `settings.json`: `vesta stop` sets `stopped` (stays down across reboots), `vesta start`/restart sets `running`. The agent never exits to restart itself: `restart_vesta`/`stop_vesta` (MCP tools in `core/tools.py`) and the dreamer's post-compaction restart call vestad over the loopback with the agent's `X-Agent-Token` (`core/vestad_client.py` -> `POST /agents/{me}/restart|stop`, dual-auth, self-scoped), and vestad performs the docker action; under `on-failure` a clean self-exit would just stay down. The one case the agent's own exit code matters is a crash: `run_vesta` returns a crashed flag, `main()` exits non-zero, and `on-failure` restarts it (intentional/clean shutdowns return False -> exit 0).

**Message flow**: a client connects to vestad's WS, which proxies to the agent container's WS port. The agent's `api.py` receives the `{type:"message"}` frame, emits a `UserEvent` to the EventBus for history + broadcast (the chat's own echo; nothing routes it to the message processor), and in the same coroutine writes a `source=app-chat` notification file, so all app chat reaches the model through the notification flow below. Intake is written in-process (not by a sidecar subscriber) so a dead process can't silently drop a message the UI already echoed as delivered; the app-chat daemon only holds a WS connection so `app-chat send` can deliver replies. The processor's queue (`message_processor` in `core/loops.py`) has exactly two producers: notification batches (`process_batch`) and boot turns (`main.py collect_boot_turns`). Turns drive the SDK client (`client.query()`) and stream response blocks (text, thinking, tool use) back through the EventBus to all WS subscribers in real time. **Preemption**: the processor's queue-watcher owns preempt delivery: an item landing mid-turn is pre-sent via `send_preempt` (`core/client.py`) as a `priority:"now"` user message, and the CLI ends the running turn at its next step boundary (a foreground tool call in flight finishes first; the latched abort applies when it returns) and runs that prompt as the next turn, with background subagents surviving (issue #982). The item is stamped `pre_sent=True` so `converse` waits on the turn without re-sending the query; the processor takes pre-sent items ahead of earlier plain items (they already jumped the CLI's queue), and a fast preempt result arriving before its Vesta turn opens is banked and claimed at open (`State.preempt_outstanding` / `preempt_orphaned_results`). The SDK `interrupt()` control request fires only on failure paths (silence/query timeout, auth loss): in headless mode the CLI's handler kills every backgrounded subagent, which is why routine preemption never uses it.

**Notification flow**: external systems write JSON files to `~/agent/notifications/` inside the container; `monitor_loop` in `core/loops.py` watches with `watchfiles.awatch()`. Each tick `notification_interrupt_policy.py` decides interrupt vs. snooze via an ordered first-match ruleset: each rule matches on `source`/`type` plus any number of `match` predicates (`FieldPredicate`: a field, `contains`/`regex` op, optional `negate`) over any notification field, with `sender`/`text` aliases spanning per-source synonyms. With no matching rule the notification's own `interrupt` flag decides, the default the producing skill ships (`Notification.interrupt` in `notification.py`: whatsapp/chat interrupt, email/finance snooze), which the ruleset overrides. Interrupting notifications preempt the current turn (see Preemption above); snoozed ones wait and are worked through in one batch once the agent has been idle a little while. The ruleset lives on `VestaConfig.notification_rules` (`~/agent/data/config.json`), read live from the store each tick (no restart) and edited by the user (`PUT /config` with `{notification_rules}`) or the agent (the `notifications` skill, a thin `GET/PUT /config` client). `source=core` notifications are exempt: their disposition is control-flow derived from the type (`CORE_SNOOZE_TYPES` in `notification.py`, decided by `loops._notif_disposition`), so a broad user rule can't swallow them. Boot-time control-flow (greeting, first-start, migrations, skill-sync, config issues) is not a notification; it is delivered as non-interruptible boot turns enqueued at startup (`main.py collect_boot_turns`) and processed in order before other work.

**Session persistence**: cross-restart state lives in `~/agent/data/state.json`, a single atomically written `PersistedState` blob owned by `state_store.py` holding the Claude SDK `session_id` (conversation resume), boot markers, `migrations.applied`, and the last dreamer run. Legacy per-marker files (the old `session_id` file, `first_start_done`, `last_dreamer_run`, etc.) are imported into it and removed on first boot. All events live in `~/agent/data/events.db` (SQLite with FTS5 full-text search). The events.db schema is versioned via `PRAGMA user_version`: `events.py` owns an ordered, version-gated `_MIGRATIONS` list applied at `EventBus` construction. Version 1 is the baseline (the current `CREATE ... IF NOT EXISTS` schema), so fresh and pre-versioned dbs both converge to v1 with no data loss; future changes add v2+ steps, and a released step is never edited. Every restart resumes the persisted `session_id`; only compaction shrinks context. Compaction is one core primitive, the `compact_context` tool (`core/tools.py`): it compacts the live session at the next idle point with caller-supplied instructions, optionally delivers a follow-up turn afterward (a live snoozed notification when it does not restart, a boot-greeting extra carried through the restart when it does), and optionally restarts into the compacted session. The drain (`loops.py:drain_compaction_request`) owns that routing and prepends the one core-owned orientation line (`COMPACTION_ORIENTATION`); skills own the rest. The nap skill (compact in place, no restart) and the nightly dream (curate memory, record via `mark_dreamer_complete`, then `compact_context(restart=true)`) compose on top; core owns only the mechanism, a generic once-consumed `pending_boot_message`, and the `last_dreamer_run` timestamp, never the feature's meaning. The `"dreamer"` runs nightly at `NIGHTLY_MEMORY_HOUR`.

**Migrations** (agent-state, distinct from the events.db schema migrations above): `migrations.py` runs prompt-based migrations, markdown files under `agent/core/migrations/`. On boot each unapplied migration is delivered as a boot turn (see Notification flow); the prompt's final step calls the `mark_migration_applied(name)` tool, which records it in `state.json`. If the agent never marks it (rate limit, crash, hallucinated success) it re-runs next boot, so migration prompts must be idempotent. Fresh agents pre-mark every shipping migration without running it; migrations exist only to converge legacy state on update. Released migrations are append-only: once shipped in a release they never re-run for already-migrated agents, so an edit reaches nobody. Converge new state with a new migration file, never by editing a shipped one, and make each migration cumulative (the beta channel lets agents skip versions; never assume the previous version was N-1).

**Upstream sync (vestad-local distribution)**: vestad embeds the complete agent home (`agent/core`, `agent/skills`, `agent/MEMORY.md`, `agent/.gitignore`). At startup, after `ensure_agent_code`, `upstream.rs` runs the embedded `vestad/scripts/build-upstream.sh` (one tested bash script owning all git logic; its suite is `agent/tests/test_build_upstream.py`) to append a snapshot commit + `agent-vX.Y.Z` tag to the per-host bare repo at `~/.config/vesta/vestad/upstream/upstream.git` (branch `agent-upstream`). That directory is bind-mounted read-only into every agent container at `/run/vesta-upstream`, and boxes `git fetch` straight from the mounted repo via the upstream-sync core skill's `fetch-upstream.sh`: no github, no network, no auth, identical in dev/tests/prod. A box's `$HOME` is a cone-mode sparse checkout (`attach.sh`; the cone = installed skills). After a vestad upgrade the running core version (read from `core/pyproject.toml`) no longer matches the persisted `last_synced_version`, so `upstream_sync.py` queues an upstream-sync boot turn: the agent rebases its local changes onto `agent-v<version>` and records completion via the `mark_upstream_synced` tool (unmarked turns re-fire every boot). Managed boxes get the engine (`agent/core/`) as one read-only mount, kept out of the checkout cone; unmanaged boxes (`--no-manage-core-code`) add `agent/core` to their cone and pull core through the same rebase. Pre-rename boxes converge through LEGACY shims (grep `LEGACY(`): a forwarding `workspace-sync` skill dir, a `mark_workspace_synced` tool alias, a dual-published `agent-workspace` branch, and the still-served `GET /agents/{me}/workspace.bundle` endpoint + `workspace.bundle` artifact. **Testing the sync turn on dev**: the version only changes at release, so force the turn by resetting the marker while the container is stopped (a running agent's graceful shutdown re-saves `state.json` from memory and would clobber a live edit): `docker stop <container>`, `docker cp <container>:/root/agent/data/state.json /tmp/s.json`, set `last_synced_version` to `0.0.0`, `docker cp` it back, `docker start`. Day-to-day content iteration needs no turn: restart vestad (appends a snapshot, moves the same-version tag) and ask the agent to sync; the rebase picks up the moved tag.

**Config (two bricks, one home each)**: agent configuration is split by kind so each value has a single owner. **Identity** (`WS_PORT`, `AGENT_TOKEN`, `AGENT_NAME`, `TZ`, tunnel): vestad writes it to `agents/{agent}.env` on the host at creation, bind-mounted read-only into the container; the agent never writes it. **Config** (the agent's instance): a single nested store at `~/agent/data/config.json`, modeled by `config.py`'s `VestaConfig`. It holds the active `provider` (a pydantic discriminated union, `ClaudeConfig | OpenRouterConfig`, carrying that provider's model + context + thinking + credential), provider-independent prefs (`agent_personality`, `timezone`, `seed_context`), and the `notification_rules` ruleset. The provider is its own resource: set/switched via `PUT /provider` (sign in), tweaked via `PATCH /provider` (model/context/thinking), cleared via `DELETE /provider` (sign out); `PUT /config` writes prefs and `notification_rules` and rejects a `provider` key. Most `PUT /config` fields apply on the next restart; `notification_rules` apply live (`monitor_loop` re-reads them each tick, so the rules editor and the `notifications` skill need no restart). One-shot boot migrations fold a legacy `notification_policy.json` (per-source defaults translated to trailing rules) into `notification_rules` and relocate legacy flat keys (`agent_model`/`agent_provider`/`openrouter_key`/...) into the nested `provider`; that is the only place flat/nested mapping lives. Credentials live per the LLM provider section below. `VestaConfig` layers pydantic-settings sources, highest first: init args, the config store (so a write overrides anything stale), env (identity + operational scalars only; the provider lives in the store, not env), then the model's own field defaults. New-agent defaults plus the per-provider catalog (model lists, context presets, thinking support) are hand-authored in `agent/core/manifest.json`, read by `config.py` as the one source of the model's field defaults (so they aren't restated in code) and served by vestad at `GET /manifest` for the non-Python (web/cli) layers; there is no generation step. Built-in prompts (notification_suffix.md, nightly_dream.md, restart.md, etc.) ship in `agent/core/prompts/` and are read from there (`core_prompts_dir`); the agent's MEMORY.md lives at `~/agent/MEMORY.md`.

**LLM provider**: each agent talks to either Claude (OAuth, the default) or OpenRouter (API key), modeled as `config.provider` (the `ClaudeConfig | OpenRouterConfig` union). The union makes illegal states unrepresentable: openrouter structurally requires a key, claude carries the thinking knob + its OAuth blob. `provider.py` owns this upstream relationship: the provider + OpenRouter key live nested in the config store (the key a redacted `SecretStr` on the wire), while the Claude OAuth blob lives in `.credentials.json` (the `claude` CLI reads and refreshes it directly), loaded into the model at boot but never persisted to the store. `client.py` injects the OpenRouter key into the SDK subprocess env, so nothing is shell-sourced at container start. Provider writes are write-only; the caller restarts the agent once afterwards to apply (provisioning is a few writes + a single restart, never a per-write restart race), and `set_claude`/`set_openrouter` merge onto the existing provider so a re-auth or a model-only patch preserves the rest. Auth state is re-derived from `.credentials.json` + the config store on every boot (disk is the single source of truth); a terminal runtime 401/402 flips it in-memory only, no persisted flag. OpenRouter traffic is proxied and cached by `openrouter_cache.py`. This is distinct from the agent's own HTTP API auth below. **Invariant: the git workspace must never track `~/.claude`.** The agent's `$HOME` is itself a sparse git checkout of this repo (the upstream-sync update mechanism), and this repo tracks dev-only Claude Code tooling under `.claude/`, the same dir holding the agent's runtime `.credentials.json` + sessions. If the workspace ever *tracks* `.claude`, a `git sparse-checkout reapply` (run by `skills-install` and by migrations) sparsifies the out-of-cone `.claude/` and deletes the untracked credentials with it. The upstream snapshot never tracks `.claude` (build-upstream.sh stages an explicit allowlist), so converged workspaces cannot hit this; the container entrypoint (`agent_container_entrypoint_cmd` in `docker.rs`) still untracks + excludes `.claude` on every boot as a LEGACY guard until the fleet has migrated off monorepo checkouts. No skill script or migration needs a per-call guard.

**Auth**: vestad generates an API key at `~/.config/vesta/vestad/api-key` (clients use a `Bearer` token or `?token=` query param). Each agent gets a unique `AGENT_TOKEN` for agent-to-vestad auth via the `X-Agent-Token` header. TLS uses self-signed certs with fingerprint verification (no CA chain).

**Constitution**: each agent has a user-authored `constitution.md` (host `agents/{name}.constitution.md`) bind-mounted read-only at `/root/agent/constitution.md`, in a separate mount from the core-code mount (`/root/agent/core`) so agent self-updates never touch it. The agent reads its constitution but cannot edit it: the user's immutable rules.

**Skills**: each skill in `agent/skills/{name}/` or `agent/core/skills/{name}/` has `SKILL.md` (YAML frontmatter with name/description) + CLI tools, loaded natively by Claude Code (via `setting_sources` + the skill directories). Installing on a box means adding the directory to the sparse-checkout cone (`skills-install`); removal drops the cone entry. `agent/skills/index.json` is auto-generated from both directories and must be committed when skills change (see [Adding a skill](#adding-a-skill)). The bracketed `[Fill in...]` placeholders in a skill's `SKILL.md` are intentional personalization scaffolding the agent fills in per user over time; leave them intact, they are not dead space.

**Backup/restore**: each backup is a `restic` snapshot in a single deduplicated, compressed, encrypted repository at `~/.config/vesta/vestad/restic-repo` (passphrase at `~/.config/vesta/vestad/restic-password`). A snapshot is `docker export <container>` streamed into `restic backup --stdin`, tagged `agent:<name>` + `type:<backup_type>`; restore is `restic dump | docker import` into a fresh container. Dedup means retaining many snapshots of a multi-GB agent costs roughly one full copy plus per-run diffs. `restic` is located on PATH or extracted from a copy embedded into the vestad binary at build time (`build.rs` vendors it into `vestad/vendored/`, `src/restic_embed.rs` bakes it in, `src/restic.rs` extracts it; same mechanism as cloudflared). Retention (3 daily, 2 weekly, 1 monthly default) is computed in `compute_backups_to_delete` and applied via `restic forget --prune`. The separate `vestad backup export/import` file path (`.tar.gz` via `docker export`) is used for cross-machine transfer. All `~/agent/` state (events.db, state.json) survives backup/restore.

## Architecture Principles

Reconciled rubric for this system. Where canonical architecture advice fights Vesta's intentional design, the design wins (see resolved conflicts at the end of this section). The Karpathy Guidelines and the working rules below govern *how* to apply these principles.

- **Elegance is the north star.** Aim for 90% of the value at 10% of the effort. Ambition means scope, never complexity: re-architect without fear, but the final state must end simpler than the start (fewer concepts, lines, states, steps). Subtraction beats addition: prefer removing a step, state, concept, or layer over adding one. Applies to code, architecture, product, and prompts (keep prompts irreducible).
- **Deep modules, hidden decisions.** When complexity is unavoidable, isolate it in one module behind a small, clearly defined interface; complexity that leaks across module boundaries is the failure mode. The Claude Agent SDK is the model: a small `ClaudeSDKClient` surface hiding the whole headless control protocol. Consume that surface; keep the SDK seam in `core/client.py` + `core/sdk_parsing.py`, do not scatter SDK internals across `loops.py`. (The dormant `cc_sdk` exemplifies the same principle for the CLI-driving path.)
- **Minimize stack depth.** Deep modules, shallow stacks: no pass-through wrappers or layers that only forward arguments. Every level between an entry point and its effect must make a real decision; inline the ones that don't.
- **Confine IO to edge modules.** Docker in `vestad/src/docker.rs`, restic in `restic.rs`, the claude driver behind the `claude_agent_sdk` client surface, SQLite + FTS5 in `agent/core/events.py`. No raw shellouts, HTTP calls, or SQL strings scattered into `loops.py`, `client.py`, or request handlers.
- **One owner per decision.** Notification format, the `agents/{name}.env` config contract, the SDK option/hook mapping (`core/client.py` builds `ClaudeAgentOptions`, `core/sdk_parsing.py` owns the hook wiring): each lives in exactly one module. A constant or format appearing in two modules moves to its owner.
- **No shared crate between `cli` and `vestad`.** The JSON/WS wire contract, the `window.vestaNative` preload API, and the `X-Agent-Token` header are the only coupling. Duplicate small DTO shapes per crate rather than sharing a library.
- **Python stays functional.** Pure functions plus dataclasses/TypedDicts/pydantic models, no classes-with-methods. Pass `State` and `VestaConfig` as explicit keyword arguments (the functional stand-in for dependency injection).
- **Minimize global state.** No module-level mutable state or singletons: state lives in explicit objects (`State`, `VestaConfig`) built at the entry point and passed down as arguments.
- **Type everything as precisely as possible.** No loose-typing escape hatches in any language: no `Any`/`object` stand-ins in Python (see the Python conventions), no `any` in TypeScript, no stringly-typed errors in Rust. Model shapes concretely and parse at the boundary so everything downstream is fully typed.
- **Banned accessors.** No `getattr`, dict `.get()` fallback, or `hasattr` in Python. No `panic!`/`unwrap`/`expect` on fallible paths in `vestad/`/`cli/` (`expect` only where failure is impossible); return `Result`.
- **Named consts, descriptive names, minimal clone (Rust).** Follow `DOCKER_TIMEOUT_SECS`, `IMPORT_PIPELINE_MAX_ATTEMPTS`, `UPSTREAM_READY_POLL_MAX`.
- **Simple data across boundaries.** JSON events on the bus, env vars across the container boundary, serde DTOs across the HTTP API. No request objects, rows, or tmux internals crossing boundaries.
- **High cohesion, no grab-bags.** `helpers.py` and `lib/` stay narrowly scoped; a module whose name needs "and" gets split.
- **Circular dependencies are BANNED.** The module graph is a DAG: if two modules need each other, either merge them or extract the shared piece into a module below both. Never break a cycle with an inline/deferred import, a callback registry, or a forward reference; those hide the cycle instead of removing it.
- **Design errors out of existence.** Prefer idempotent no-ops (`unlink(missing_ok=True)`, `mkdir(exist_ok=True)`, restic dedup) over special-case error branches.
- **Surgical by default; restructure when the structure forces a workaround.** Default to the smallest change that solves today's problem: match surrounding style, don't refactor working code for taste, remove only the orphans you create, no speculative flexibility for a single caller. But surgical is never a license to graft a workaround onto a structure that can't hold it: when a local fix would force duplication, a non-scalable interface, or new coupling, fix the structure instead; that change still traces to the request, and the workaround is the expensive choice (half-right interfaces, bugs that span seams, coupling the next change inherits). The bar for touching more code is "the current shape forces a worse change", not taste. When genuinely torn between the surgical patch and a rounded fix that touches more code but pays off long-term, do not pick silently: lay out both (blast radius now vs. long-term gain, what each leaves behind) and let the user choose.
- **One fix per root cause.** Once you've found the actual cause, fix it at that one layer; do not stack a redundant defensive guard elsewhere "just in case". Overlapping fixes accumulate, the next debugger can't tell which one matters, and each layer masks the next. If a second layer seems necessary you haven't found the root cause; keep looking. Prefer deleting a now-redundant guard over adding another.
- **Minimize comments; a long comment is a code smell.** Write a comment only when really necessary: a non-obvious mechanic the code cannot show (cc_sdk double-Escape, the watchfiles local-stop bridge, the circular dreamer window), in present tense: what the code does now, never how it used to be (no "previously", "no longer", "moved from"). If a workaround or a piece of functionality needs a paragraph-long comment to explain, the code is overly complicated: simplify the code instead of writing the comment.
- **Reason about the fleet, not just the repo.** Agents are long-lived containers carrying per-user state and personalization; a change that is clean in the repo can silently strand them on update. If a change moves, renames, or deletes anything an agent already has on disk or in config (installed-skill cone, data dirs, env vars, personalized files, registered services), ship an idempotent prompt migration under `agent/core/migrations/` in the same PR, and prefer keeping internal contracts (commands, paths, env vars) stable to shrink the blast radius.
- **Mark transitional code for removal.** Code that exists only to converge old fleet state (back-compat shims, fallback config sources, one-shot renames) carries a grep-able marker so it can be found and deleted once justified: `LEGACY(remove-when: <concrete, checkable condition>): <what and why>`. The condition must be evaluable later (a version, a date, or a fleet state), never "someday". Enumerate with `rg 'LEGACY\('`; when the condition holds, delete the marked code and its tests in one PR. Prompt-based migrations under `agent/core/migrations/` are inherently legacy and don't need the marker; everything else does.

**Conflicts resolved (our design wins):** circuit breakers, per-dependency bulkhead pools, load-shed 429s, and golden-signal dashboards are skipped: Vesta is a single-tenant personal daemon where timeout + capped-retry + supervised-restart already bound blast radius. Formal ADR/C4 docs and SCA/SLSA supply-chain ceremony are replaced by this CLAUDE.md plus the memory feedback files as the in-repo decision record. Port/adapter interface objects are replaced by explicit-config-passing because Python is intentionally class-free.

## Karpathy Guidelines

Behavioral guidelines to reduce common LLM coding mistakes, derived from [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876). They bias toward caution over speed; for trivial tasks, use judgment.

### 1. Think Before Coding

Don't assume, don't hide confusion, surface tradeoffs. Before implementing: state your assumptions explicitly, and ask if uncertain. If multiple interpretations exist, present them, don't pick silently. If a simpler approach exists, say so; push back when warranted. If something is unclear, stop, name what's confusing, and ask.

### 2. Simplicity First

Minimum code that solves the problem, nothing speculative: no features beyond what was asked, no abstractions for single-use code, no "flexibility" or "configurability" that wasn't requested, no error handling for impossible scenarios. If you write 200 lines and it could be 50, rewrite it. Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

Touch only what you must; clean up only your own mess. Don't "improve" adjacent code, comments, or formatting; don't refactor things that aren't broken; match existing style even if you'd do it differently. If you notice unrelated dead code, mention it, don't delete it. Remove imports/variables/functions that YOUR changes made unused; don't remove pre-existing dead code unless asked. The test: every changed line traces directly to the user's request. This governs taste-driven changes only; it is never a license to work around bad structure (the Surgical principle above says when the structural fix *is* the request, and to present both options when genuinely torn).

### 4. Goal-Driven Execution

Define success criteria; loop until verified. Transform tasks into verifiable goals: "Add validation" -> "Write tests for invalid inputs, then make them pass"; "Fix the bug" -> "Write a test that reproduces it, then make it pass"; "Refactor X" -> "Ensure tests pass before and after". For multi-step tasks, state a brief plan of steps each with a verify check. Strong success criteria let you loop independently; weak criteria ("make it work") require constant clarification.

## Project layout

Each crate/app is standalone; see [Architecture](#architecture).

```
agent/        # async Python agent (uv), entry point core/main.py
cli/          # vesta client (standalone Rust crate)
vestad/       # vestad daemon (standalone Rust crate) + tests-integration/
apps/web/     # React + TypeScript SPA (@vesta/web)
apps/desktop/ # Electron wrapper (macOS/Windows/Linux)
agent/skills/ + agent/core/skills/  # skills (SKILL.md + scripts)
```

## Commands

> **Skills index**: when adding or modifying skills, run `uv run python agent/skills/generate-index.py` and commit `agent/skills/index.json`. CI fails if the index is stale.

### check.sh (single entry point, run from repo root)

CI runs these exact subcommands, so passing locally means passing CI:

```bash
./check.sh agent          # ty check + pytest (incl. cc_sdk transport tests; needs tmux)
./check.sh guards         # repo-wide ruff check + format, skills index, uv.lock, dashboard-sync freshness
./check.sh cli            # cargo clippy -D warnings + cargo test
./check.sh vestad         # cargo clippy -p vestad -D warnings + cargo test -p vestad
./check.sh vestad-docker  # vestad #[ignore] Docker tests (needs Docker + agent image)
./check.sh web            # eslint + prettier --check + tsc + vitest
./check.sh integration    # vestad integration tests (needs Docker)
./check.sh live           # live agent e2e (Docker + CLAUDE_CREDENTIALS; real Claude)
./check.sh all            # guards + agent + cli + vestad + web
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
npm -w @vesta/desktop run dev              # Desktop dev: vite dev server + electron window with hot reload
npm -w @vesta/desktop run build            # Package the desktop app (electron-builder, artifacts in apps/desktop/dist)
```

### Releasing

```bash
./release.sh "<message>"         # Patch release (0.1.0 -> 0.1.1)
./release.sh minor "<message>"   # Minor release (0.1.0 -> 0.2.0)
./release.sh major "<message>"   # Major release (0.1.0 -> 1.0.0)
```

The message is required: user-facing "What's new" marketing copy embedded in the release body (the app and changelog parse it). Pull a broken beta with `./unrelease.sh vX.Y.Z`; promote a soaked one with `./promote.sh vX.Y.Z`.

Run locally on master. Bumps versions, updates lockfiles, commits, pushes, and creates the GitHub release. CI then builds artifacts and publishes. Do NOT bump versions in PRs: `release.sh` handles version bumps at release time.

## Code conventions

### Brand voice
- **Positioning (the single source of truth for Vesta's copy).** Vesta is an **AI guardian angel**. Not a "personal AI", not an "assistant", not a friend or companion. The canonical one-liner, used verbatim wherever a tagline is needed: **"an AI guardian angel that gives you back time and helps you achieve your goals."** Every user-facing surface (README, landing, app strings, prompts, emails, CLI output) draws its positioning from here; never reintroduce "personal AI"/"personal assistant" framing.
- **Never use a pronoun for Vesta.** In all copy and prose, refer to the agent as **"Vesta"**, or **"they/them/their"** where a pronoun is unavoidable. Never "she/her" or "it/its". This holds across every surface: README, app/notification strings, agent prompts and skills, and the vesta-cloud site and emails. The product is a relationship, not a gadget; one consistent voice keeps each new email or prompt from re-litigating it. (This does not apply to pronouns for other nouns: the daemon, a container, the user, a config object.)
- **No dashes as separators in prose.** In prose and copy (this file, SKILL.md bodies, prompts, app strings, PR descriptions, emails), never use spaced-hyphen or em-dash separators; use commas, periods, or colons instead.

### Python (agent/)
- **Always `uv run`**, never bare `python`
- **`getattr`, `.get()` (dict), `hasattr` are banned**: use direct access, `in` checks, or try/except
- **`tp.Any` and `object` are banned as loose types** (including `dict[str, Any]`/`dict[str, object]`): model shapes as pydantic models or TypedDicts and parse at the boundary; use `pydantic.JsonValue` for genuinely dynamic JSON; `tp.cast` only to a concrete type, never to `Any`/`object`
- **No silent exception swallowing**: prefer explicit checks (`if path.exists()`) or log the error
- Line length: 144 (ruff)

### Async Python (agent/)
- **No blocking calls in coroutines**: no `time.sleep`, `requests`, sync `subprocess`/`open`/`input`, or inline CPU-heavy work inside an `async def`. Use `asyncio.sleep`, an async client, `create_subprocess_exec`, or `asyncio.to_thread`/`run_in_executor`.
- **Own your tasks**: keep a strong reference to every `create_task` (e.g. a set with `add_done_callback(set.discard)`) and consume its exceptions (await, inspect `task.exception()`, or use a `TaskGroup`). Never fire `create_task` as a bare statement.
- **Respect cancellation**: in `except asyncio.CancelledError` do cleanup then re-raise. Do not put unshielded `await` in `finally` cleanup. From a non-loop thread use only `call_soon_threadsafe`/`run_coroutine_threadsafe`.
- **No mutable default args**: default to `None`, build inside the body. Compare to `None` with `is`/`is not`.
- Log with `%`-style placeholders (`logger.info("x=%s", value)`), not pre-formatted f-strings.

### Rust (cli/, vestad/)
- **No panics in library/server code**: return `Result`, never `panic!()` or `.unwrap()` on fallible operations. `.expect()` only where failure is truly impossible.
- **Named constants for magic numbers**: timeouts, buffer sizes, port numbers, retry counts go in `const` at the top of the file.
- **Descriptive variable names**: no single-letter vars (`n`, `t`, `c`). Use `name`, `tag`, `client`.
- **Minimize `.clone()`**: move values into closures when possible, only clone when the value is genuinely needed afterward.
- **Extract repeated patterns**: if 3+ lines appear twice, extract a helper function.
- **Error types**: public errors implement `std::error::Error` and are `Send + Sync + 'static`; never `()` or bare `String`. `Display` messages are lowercase, no trailing punctuation, source chained via `Error::source`.
- **Private fields by default**, access via methods; public fields only for plain data structs with no invariants. Keep derivable bounds on the `derive`/`impl`, not the type definition.
- **Eagerly derive** `Debug` (non-empty) plus `Clone`/`Copy`/`PartialEq`/`Default` where correct; `Box` oversized enum variants.
- **Typed args** over unlabeled `bool`/`Option` flags; group args into a struct/builder past ~5 to 7. No lossy `as` casts for fallible conversions (use `From`/`TryFrom`); avoid catch-all match arms when exhaustive handling is feasible. Every `unsafe` block carries a `// SAFETY:` justification.

### Frontend (apps/web/src/)
- **"Agent" terminology everywhere**, never "box". Types: `AgentInfo`, `AgentConnection`, `AgentActivityState`.
- **The `window.vestaNative` preload API is the desktop wire contract**: `apps/desktop/src/preload.ts` and `apps/web/src/lib/native/types.ts` declare it twice and must stay field-for-field identical, don't rename fields on one side.
- **Hook placement**: hooks used only by a single provider live in that provider's folder (e.g. `providers/VoiceProvider/use-voice-input.ts`); `hooks/` is reserved for hooks shared across components/providers.
- **Components in folders**: each component gets a folder with `index.tsx` and optionally `styles.ts`.
- **No dividers inside cards**: never separate sections within a card with a divider line (`border-t`/`border-b`, `<Separator>`, `<hr>`); group with spacing (`gap`, padding). A hard preference, not case-by-case.
- **Rules of Hooks**: call Hooks only at the top level of a component or custom Hook, only from React contexts. Keep render pure (no side effects, no mutating props/state/context).
- **Effects are a last resort**: compute derived data during render (or `useMemo`), put interaction logic in event handlers. Every Effect has complete deps (`react-hooks/exhaustive-deps`), one concern, and cleanup for any subscription, timer, listener, or fetch (ignore/abort flag).
- **Stable list keys** from data identity, never array index for reorderable lists; reset state with a `key` prop, not an Effect.
- **Strict TS**: `strict: true`; no `any` (use `unknown` and narrow), avoid `as`/`!` assertions, annotate object literals rather than asserting, strict equality except `== null`, named exports.

## Adding a skill

Skills are how Vesta reaches the world; each is a directory the agent (and Claude Code) loads natively. Two locations: `agent/skills/{name}/` for most skills, `agent/core/skills/{name}/` for built-ins shipped with the agent (e.g. `app-chat`). Every skill has a `SKILL.md` with YAML frontmatter (`name` + `description`):

```markdown
---
name: tasks
description: Tasks, to-dos, reminders, time-based alerts; create and manage. Requires daemon.
---

# Tasks + Reminders (CLI: tasks)

<usage, commands, examples: the body the agent reads when the skill activates>
```

The **`description` is discovery text**: it's what the agent sees when deciding whether to use the skill, so write it as *when to use / triggers*, not just a label. Keep it tight.

If the skill ships a CLI, put it in a `cli/` subdirectory as its **own standalone `uv` project** (`cli/pyproject.toml` + `cli/uv.lock`) with tests under `cli/tests/`; run them with `uv run pytest skills/{name}/cli/tests/` (from `agent/`).

**Always regenerate the index** after adding or editing a skill, and commit it: `uv run python agent/skills/generate-index.py` rebuilds `agent/skills/index.json` from the `name` + `description` frontmatter across both skill directories. CI fails if it is stale, so commit it in the same PR.

## Testing strategy

- **`check.sh` is the only entry point.** Every suite (`agent`, `cli`, `vestad`, `vestad-docker`, `web`, `integration`, `live`) runs through it; CI calls the same subcommands so local equals CI. Do not add a CI step that bypasses it.
- **Keep the pyramid.** Fast in-process pytest and Rust `--bins` unit tests are the default loop; Docker-gated suites are the middle tier; `live` (real Claude) is the tiny apex run only on release. Do not push Docker- or Claude-dependent assertions into the fast tiers.
- **Prefer the high-fidelity fake over mocks.** Drive cc_sdk tests through `tests/fake_claude.py` (a real fake claude TUI in real tmux) and exercise the real EventBus/SQLite. Reserve patching for true edges (file times, credentials presence). Keep `fake_claude.py` faithful to the real claude protocol; the e2e transport tests hold it to that contract.
- **Hermetic and deterministic.** Each test builds its own tmpdir db / notifications dir and passes in isolation and any order. No shared `events.db`, no wall-clock ordering, no dependence on a running agent.
- **Never `sleep()` to await a condition.** Poll with a timeout (`tests/wait_util.py`) or drive the event-driven loops via their `asyncio.Event` signals.
- **Test observable behavior through public surfaces.** Emit a `UserEvent` and assert the resulting event stream / persisted state, not which internal function fired. Behavior names read as sentences.
- **Table-driven tests are fine; keep logic out of test bodies.** Parametrize repetitive cases (`@pytest.mark.parametrize`, Rust table tests) rather than copy-paste, but no computed expected values or conditionals in the body itself. The sanctioned exception is hypothesis property tests (`test_property.py`).
- **Beyonce rule, mapped to suites.** Crash recovery / resume -> `test_crash_recovery.py`; priority-now preemption -> `test_preempt.py`; failure-path interrupts / compaction -> `test_interrupts.py`; notification batching -> `test_notifications.py`; backup/restore and ports -> vestad tests; skill-index freshness -> CI. If you do not want it to break, it has a test.
- **Coverage is a diagnostic, never a gate.** Do not add a coverage threshold. A line is tested only when a behavioral assertion exercises it.
- **Red is stop-the-line.** A failing main branch or `check.sh` suite is reverted or fixed forward immediately. When a flaky test surfaces (e.g. the integration suite needs a retry), quarantine or fix it, do not blanket-rerun.
- **Reliability is tested, not assumed.** Every finite timeout, capped retry (`retry_import_pipeline`), single-shot session-resume guard, cancellation path, and `finally`-block resource release has behavioral coverage.

**Tests ship with logic changes** in the same PR; no permanently skipped or panic-only tests, assert concrete values.

## CI

One workflow (`ci.yml`) runs on push to `master`, PRs, and releases; jobs are path-filtered on PRs. The check/test jobs call `./check.sh` subcommands, so CI and local checks are identical by construction. Checks: version sync across sources (`agent/pyproject.toml`, `vestad/Cargo.toml`, `cli/Cargo.toml`, `vestad/tests-integration/Cargo.toml`, `apps/desktop/package.json`, `apps/web/package.json`), ruff, ty, cargo clippy, pytest (incl. cc_sdk e2e transport tests under tmux), `uv.lock` freshness. The single required branch-protection check is `merge-gate-ci`.

Docker-based jobs (integration tests, vestad Docker unit tests, live tests) build the agent image **from the checkout** (GHA layer cache) and run with `VESTAD_AGENT_IMAGE=vesta:local`, so PRs are validated against their own agent code and Dockerfile, never the previously released image.

A live agent e2e job (`test-live`) runs a real agent against real Claude using the `CLAUDE_CREDENTIALS` OAuth secret **only on the release event** (not PRs; it is slow and spends API tokens) and gates the release: a failure blocks publishing artifacts and the `:latest` image. Releases are triggered by `gh release create` (via `./release.sh`). Desktop builds from `apps/desktop` (Electron, no Rust): a universal signed + notarized dmg/zip on macOS, deb/rpm on Linux, NSIS on Windows, plus the `latest*.yml` manifests electron-updater reads.

## Pull requests

- **Never push to master.** Every change lands through a PR, urgent hotfixes included. Pushing to a feature branch needs no confirmation.
- **Work in a git worktree per branch.** Parallel sessions may hold other branches; keep the main checkout clean.
- **One concern per PR.** Isolate renames/moves and dependency bumps (manifest plus lockfile together) from logic changes. Add new dependencies conservatively and justify any new cross-module edge.
- **Conventional Commits** subjects (`feat`, `fix`, `refactor`, etc.), imperative mood, no trailing period, no closing keywords or @mentions in commit messages (those go in the PR body).
- **Tests ship with logic changes** in the same PR.
- **Do NOT bump versions in PRs**: `release.sh` handles version bumps at release time.
- **Update the skills index** when adding or modifying skills: run `uv run python agent/skills/generate-index.py` and commit `agent/skills/index.json` (CI fails if it is stale).
- Run the relevant `./check.sh` subcommands before pushing. The single required branch-protection check is `merge-gate-ci`.
- **A PR is done only when CI is green and it is mergeable.** After pushing, verify mergeability and resolve conflicts; do not report a PR as finished before `merge-gate-ci` passes.

# External restart-reason interface

**Date:** 2026-07-05
**Status:** Design approved, pending spec review

## Problem

When something restarts an agent from *outside* the container — the app's restart button,
a `vestad` backup, or (the motivating case) applying a newly-granted host mount — the agent
boots with no idea *why*. It just took a `SIGTERM` and came back. For mounts specifically,
the user grants a folder in the UI, the agent is recreated, and it silently has new
filesystem access it was never told about.

The agent already surfaces a "why you're awake" line on boot: `_consume_restart_reason`
reads `state.persisted.last_restart_reason` and feeds it as `greeting_reason` into the
greeting boot turn. But that field is only ever written *by the agent, from inside the
container* — on a crash (`main.py` error handlers), on the dreamer's self-restart
(`tools.py`), else it defaults to `CLEAN_RESTART`. An external actor has no way to set it.

## Key finding: the channel is half-built and currently dead

`vestad` already writes an external restart reason into the container — and the agent never
reads it. `backup.rs` calls:

```rust
docker_cp_content(docker, &cname, "backup — paused for backup", "/root/agent/data/restart_reason")
```

before stopping an agent for a backup. `docker_cp_content` (docker.rs) is the only caller,
and **nothing in the agent or the container entrypoint reads that file.** So the write is
inert: vestad supplies a reason that is silently dropped.

This design completes that channel and exposes it as a general interface. The writer half
already exists; the load-bearing missing piece is the agent-side reader.

## One store, one delivery channel

There is exactly **one store** for "why this boot happened":
`state.persisted.last_restart_reason` in `state.json`. It stays the single source of truth
and keeps its second job of gating the exit code (a `crash:`/`error:` reason makes the agent
exit non-zero so Docker's `on-failure` policy recovers it).

The problem is only that an *external* actor can't reach that store: `vestad` must not write
`state.json` (the running agent re-saves it from memory on shutdown and would clobber the
edit). So we give it a **delivery channel**, not a second store:

- A transient inbox file `/root/agent/data/pending_restart_reason`.
- `vestad` (host) writes it before it stops/recreates the container.
- On the next boot the agent **drains** it into `last_restart_reason` and deletes it.

At rest there is only ever the one field; the file exists only in the window between a
`vestad` write and the next boot, then it's gone — a message in a queue, not a parallel copy.
Naming it `pending_restart_reason` (distinct from the `last_restart_reason` store) keeps that
role obvious: it is an incoming reason awaiting consumption, not a second copy of the record.

**Payload:** a short human-readable string. Plain text — no JSON, no schema shared across the
crate boundary.

## Reader (agent) — the missing piece

The drain happens at the single existing consumption point, `_consume_restart_reason`, before
it reads the field:

1. If `~/agent/data/pending_restart_reason` exists, read + strip it, assign it to
   `state.persisted.last_restart_reason`, and `unlink` the file (one-shot).
2. Then the function proceeds exactly as today: return the field, clear it, save state.

The result flows unchanged into `greeting_reason` → the greeting boot turn, rendered per the
standardized format below. Absent inbox file → today's behavior, unchanged.

**Why draining is safe and unambiguous:** a `vestad`-driven restart exits the agent cleanly,
so the field would otherwise be `CLEAN_RESTART`; draining overwrites that placeholder with the
specific reason. A crash reason is agent-set and only occurs when `vestad` was *not* involved
(so no inbox file exists), meaning the two never realistically co-occur. If they somehow did,
the external file wins for that boot; the inbox payload is plain text and never carries a
`crash:`/`error:` prefix, so `_is_crash_reason` is unaffected and the exit-code path is
untouched.

## Writer (vestad)

- **Extract one helper**, `write_pending_restart_reason(docker, name, reason)`, as the single
  owner of the inbox path + `docker_cp_content` recipe. `backup.rs` switches to it (renaming
  the path from `restart_reason` to `pending_restart_reason`) and stops being a dead write —
  the agent will now surface "I was paused for a backup."
- **Mounts (motivating caller):** `restart_agent` already computes the actual-vs-desired mount
  diff to decide whether to rebuild. In that branch it synthesizes a `mounts:` reason from the
  full delta (adds and removes together — one `PUT /mounts` can change several at once) before
  recreating. **No app or API change needed** — vestad has the diff. Copy generator:
  - only grants: `mounts: you now have access to /media/Plex (read-only) and /downloads (read-write)`
  - only removals: `mounts: your access to /media/Plex and /old was removed`
  - both: `mounts: filesystem access changed. granted: /media/Plex (read-only); removed: /old`
- **The general interface:** `POST /agents/{name}/restart` gains an optional `{reason}` field.
  When present, vestad writes it before the restart. This is the interface external callers use
  to attach a human reason — e.g. the app, after a provider change, restarts with
  `manual: switching to Claude Opus 4.8` (it knows the model it just set).

## Standardized reason copy and boot message

Every reason is a single `category: detail` string; `category` is a fixed small set, `detail`
is a lowercase plain-language phrase with no trailing period and no em/en dash. The `category`
is a machine tag (`_is_crash_reason` keys on `crash`/`error`); it is **not shown** to the agent.

| Category | Copy |
|---|---|
| `clean` | `clean: routine restart, no specific reason` |
| `nightly` | `nightly: the dreamer ran and compacted your session for continuous context` |
| `crash` | `crash: {detail}` (e.g. `crash: the processor exited unexpectedly`) |
| `error` | `error: {detail}` (e.g. `error: a turn failed to complete`) |
| `backup` | `backup: you were paused for a scheduled backup` |
| `mounts` | `mounts: {delta}` (see the generator above) |
| `manual` | `manual: {caller-supplied}` (e.g. `manual: switching to Claude Opus 4.8`) |

**Render (`build_restart_context`).** The stored `category: detail` is split on the first
`": "`; only the detail is shown, under a clear restart header:

```
[System Restart]
Reason: {detail}

Read the `restart` skill and follow it.
```

A pending dreamer summary still slots between the `Reason:` line and the `restart.md` line.
`restart.md` drops its leading "You've restarted." — the `[System Restart]` header now carries
that, avoiding the doubled statement (per the "no redundant instructions" guidance). If a
stored reason somehow lacks a `category: ` prefix, the whole string renders as the detail.

## Scope

**In:**
- Agent-side drain in `_consume_restart_reason` + an inbox-path constant + unit tests.
- Standardized reason copy (the constants in `models.py` + the crash/error/dreamer strings)
  and the new `[System Restart]` / `Reason:` render in `build_restart_context`; `restart.md`
  drops "You've restarted."
- `write_pending_restart_reason` helper; `backup.rs` routed through it; path renamed to
  `pending_restart_reason`; its copy standardized to `backup: …`.
- Optional `{reason}` on `POST /agents/{name}/restart`.
- Mount-drift branch of `restart_agent` writes a synthesized `mounts:` reason (multi-mount).

**Out (follow-ups, not this change):**
- Wiring the web app to *send* a reason on manual restart. The API accepting `{reason}` is the
  interface; the app populating it is a separate enhancement.
- Any richer structured reason (multiple deltas, i18n). Plain string is sufficient.

## Testing

- **Agent** (`tests/test_processor.py`, near the existing `test_restart_reason_round_trip`):
  inbox present → `_consume_restart_reason` returns its content and the file is removed; inbox
  present over a persisted `CLEAN_RESTART` → inbox wins; inbox absent → existing behavior.
- **Agent render:** `build_restart_context` strips the `category:` prefix and emits the
  `[System Restart]` / `Reason:` block; a prefix-less reason renders whole; `_is_crash_reason`
  still true for `crash:`/`error:` categories.
- **vestad:** `write_pending_restart_reason` writes the agreed path (docker-gated); the mount
  reason generator (only-grants / only-removals / both, single and multi) as a pure unit test.

## Blast radius

- **Agent:** a file read + `unlink` folded into `_consume_restart_reason`, one path constant,
  tests. No change to the crash/exit path or `state.json` schema.
- **vestad:** extract one helper, rename one path, one optional API field, one call in the
  mount-drift branch. No new IO pattern (`docker_cp_content` exists), no cross-crate schema
  coupling (plain string).
- **web:** none.

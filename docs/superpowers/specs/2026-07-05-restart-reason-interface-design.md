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

## The contract

A one-shot plain-text file at `/root/agent/data/last_restart_reason`.

- **Writer:** `vestad` (host), via `docker_cp_content`, before it stops/recreates the container.
- **Reader:** the agent, once, on boot.
- **Payload:** a short human-readable string. Plain text — no JSON, no schema shared across
  the crate boundary.
- **Lifecycle:** written before a restart, read exactly once on the next boot, then unlinked.
  Absent file → today's behavior, unchanged.

The file is named `last_restart_reason` to match the concept the agent already uses
(`state.persisted.last_restart_reason`). It is the same value — the reason for this boot —
just supplied from outside instead of from the agent's own prior run. The rename from the
current `restart_reason` path is safe: nothing reads the old name, and the file is transient,
so no compatibility shim is needed.

## Reader (agent) — the missing piece

`_consume_restart_reason` resolves the effective reason on boot with a single clear precedence:

1. **External file** `~/agent/data/last_restart_reason`, if present — read it, strip it, and
   `unlink` it (one-shot).
2. Otherwise the agent-persisted `state.persisted.last_restart_reason` (crash / dreamer).
3. Otherwise `CLEAN_RESTART`.

The resolved reason flows unchanged into `greeting_reason` → the greeting boot turn, so the
agent naturally says e.g. "you're awake — you now have read-only access to `/media/Plex`."

**Why the two sources don't collide:** a crash reason is agent-set in `state.json` on the
*prior* run and only occurs when vestad was *not* involved (the agent crashed and Docker's
`on-failure` recovered it); a file reason is only written when vestad drives the restart, in
which case the agent exits cleanly and persists `CLEAN_RESTART`. They are mutually exclusive
in practice. The file reason is plain text and never starts with `crash:`/`error:`, so it is
correctly treated as a clean reason.

**Interaction with crash/exit logic is none:** `_is_crash_reason` runs at *shutdown* against
the field the current run sets for its *own* exit code — a separate concern from the boot
reason the file feeds. The file is consumed only at boot.

## Writer (vestad)

- **Extract one helper**, `write_restart_reason(docker, name, reason)`, as the single owner of
  the path + `docker_cp_content` recipe. `backup.rs` switches to it (and stops being a dead
  write — the agent will now surface "I was paused for a backup").
- **Mounts (motivating caller):** `restart_agent` already computes the actual-vs-desired mount
  diff to decide whether to rebuild. In that branch it writes a reason describing the delta
  (e.g. "granted read-only access to /media/Plex") before recreating. **No app or API change
  needed** — vestad synthesizes it from the diff it already has.
- **The general interface:** `POST /agents/{name}/restart` gains an optional `{reason}` field.
  When present, vestad writes it before the restart. This is the interface external callers
  (app "restart" button, CLI) use to attach a human reason.

## Scope

**In:**
- Agent-side reader in `_consume_restart_reason` + a path constant + unit tests.
- `write_restart_reason` helper; `backup.rs` routed through it; path renamed to
  `last_restart_reason`.
- Optional `{reason}` on `POST /agents/{name}/restart`.
- Mount-drift branch of `restart_agent` writes a synthesized reason.

**Out (follow-ups, not this change):**
- Wiring the web app to *send* a reason on manual restart. The API accepting `{reason}` is the
  interface; the app populating it is a separate enhancement.
- Any richer structured reason (multiple deltas, i18n). Plain string is sufficient.

## Testing

- **Agent** (`tests/test_processor.py`, near the existing `test_restart_reason_round_trip`):
  file present → `_consume_restart_reason` returns its content and the file is removed; file
  absent → existing behavior; file present alongside a persisted clean reason → file wins.
- **vestad:** `write_restart_reason` writes the agreed path (docker-gated); the mount-drift
  restart writes a reason (docker-gated, alongside the existing recreate coverage).

## Blast radius

- **Agent:** one file read + `unlink` in `_consume_restart_reason`, one path constant, tests.
- **vestad:** extract one helper, rename one path, one optional API field, one call in the
  mount-drift branch. No new IO pattern (`docker_cp_content` exists), no cross-crate schema
  coupling (plain string).
- **web:** none.

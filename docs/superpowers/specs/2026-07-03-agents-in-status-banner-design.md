# Agents in the vestad status banner — design

**Date:** 2026-07-03
**Status:** approved

## Goal

`vestad status` shows each agent's live status. Every banner path (daemon startup and
`vestad status`) shows the number of agents and their names.

```
── agents (2) ─────────────────────
vesta      alive
backup     stopped
```

At daemon startup the status column is empty (agents are just being started by
`reconcile_containers`; any status printed then would be stale seconds later).

## How the status crosses the process boundary

`vestad status` is a separate process from the daemon, so it cannot read the daemon's
in-memory `AgentStatusCache`. Rather than adding an HTTP client + tokio runtime to the
status command, the daemon persists its cached agent list into `status.json` — the file
`vestad status` already loads, pid-gated so a dead daemon's snapshot is never shown.

Rejected alternative: `GET /agents` from the status command. It gives fresher data
(the file is at most ~3s stale, one cache poll) but requires a runtime (reqwest's
`blocking` feature is not enabled), a timeout, and a fallback branch. Staleness of a
few seconds is acceptable for a status command.

## Changes

### `docker.rs`

- `AgentStatus` derives `Deserialize` (it already serializes `snake_case` into the
  `GET /agents` responses; `Status::load` now needs to read it back).
- A human-text helper next to the enum (one owner): `alive`, `setting up`,
  `not authenticated`, ... — snake_case with spaces.
- `env_file_names` becomes `pub(crate)` so `main.rs` can seed agent names at boot
  without re-implementing the read_dir.

### `status.rs`

- `Status` gains `agents: Vec<AgentEntry>`; `AgentEntry { name: String, status:
  Option<AgentStatus> }` lives here — this module owns the `status.json` format.
- `BoxRow::Kv` label widens from `&'static str` to `String` (mechanical `.into()` at
  the existing call sites). Agent names are runtime values, and `print_banner`
  pre-pads them to `max(BANNER_LABEL_W, longest_name + 2)` so the status column stays
  aligned for names longer than the fixed 9-char label column.
- `print_banner` renders a `── agents (N) ──` rule followed by one row per agent;
  the status column renders the human text, or empty when `None`. Zero agents renders
  the rule with `(0)` and no rows.

### `main.rs` (daemon boot)

- `Status::new` gains the agents vector; boot seeds it with names from the env files
  (`docker::env_file_names`), statuses `None`. Banner prints count + names.

### Live updates (mirrors `on_tunnel_up`)

- `main.rs` builds `on_agents_changed: Arc<dyn Fn(Vec<ListEntry>) + Send + Sync>`
  capturing the existing `Arc<Mutex<Status>>` + config dir: it maps `ListEntry` →
  `AgentEntry`, swaps `Status.agents`, persists.
- Threaded through `ServerConfig` → `serve::run_server` → `spawn_agent_status_task`.
- The polling task invokes it exactly when `agents_tx.send_if_modified` reports a real
  change, so `status.json` is rewritten only on agent transitions (boot churn, then
  quiet).

### `vestad status`

Mechanically unchanged: load `status.json`, pid-gate, render. Statuses appear because
the daemon persisted them (at most ~3s stale).

## Testing

- `status.rs` unit tests: agent rows render with and without statuses; count appears
  in the rule; zero-agent case; long-name column alignment.
- Round-trip test extended to cover `agents` (exercises `AgentStatus` Deserialize),
  mirroring `status_json_round_trips_all_tunnel_states`.

## Out of scope

- The `Status` command's existing header line (`vestad vX (path, N agents)`) keeps its
  count — partially redundant with the new section, left alone (surgical).
- No changes to `GET /agents`, `AgentStatusCache` semantics, or the web app.

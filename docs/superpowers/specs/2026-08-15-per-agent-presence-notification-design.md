# Per-agent presence notification

## Problem

Today the `user-presence` notification is a **global** signal. The `/sync` socket
reports one `focused` boolean (app-level presence). When the user returns after
being away at least ten minutes (`PRESENCE_NOTIFY_DEBOUNCE`) and stays at least
45 seconds (`PRESENCE_NOTIFY_DELAY`), vestad fans a `user-presence` notification
out to **every** tapped agent with `presence_notifications.enabled`.

We want presence to be **per agent**: when the user opens a specific agent's
page, only that agent learns the user is here. Opening the app in general, or
sitting on the roster, notifies no one.

## Semantics (locked)

- **Trigger:** the user opens a specific agent's page.
- **Gate:** notify agent X only if the user has **not** viewed agent X in the
  last ~10 minutes. Each agent is independent.
- **Dwell:** after opening X's page, wait ~45 seconds; notify only if X is still
  the open page. Filters rapid click-through across agents.
- **Not a trigger:** app focus alone, the roster/home screen, or a non-agent
  screen. Those report no viewed agent, so no one is notified.

The two knobs keep their current values and meaning; only the key changes from a
single global timeline to one timeline per agent.

## Approach

Extend the existing presence machinery to be **per-agent-keyed**. Reintroduce a
per-agent "which agent am I viewing" signal on `client_context` and re-key
vestad's presence state from one global timeline to one per agent. The 10-minute
gate and 45-second settle logic (including the glance, resync, and
pending-frozen rules) carry over unchanged, keyed by agent name.

Two rejected alternatives:

- **Global trigger, narrow fan-out.** Keep the global "away ≥10 min → return"
  trigger, drop into only the currently-viewed agent at fire time. The gate
  stays global, so switching agents while already active never notifies.
  Contradicts the per-agent gate.
- **Client decides.** Move the debounce/dwell policy into web and mobile and let
  them tell vestad "notify X now." Duplicates policy across clients and breaks
  "vestad owns presence policy."

## Design

### 1. Wire signal

Add one optional field to the `client_context` frame:

- `viewing: string | null` — the agent whose page is open on that client, or
  `null` when the client is on the roster/home, on a non-agent screen, or the
  window is blurred. The client computes it as
  `windowFocused && onAgentRoute ? agentName : null`.
- `focused` stays unchanged and still drives the global `any_focused` fan-out
  (cross-device notification muting). `viewing` is purely the presence-
  notification trigger.

`viewing` is additive and unknown-field-ignored on both sides, so
`MIN_SUPPORTED_CLIENT_VERSION` does **not** move. A shipped client that never
sends `viewing` simply never triggers a per-agent presence notification, which
is the safe direction. (The retired `active_agent` field is unrelated; it stays
ignored.)

### 2. Server presence state (`vestad/src/sync/presence.rs`)

Re-key the presence state per agent:

- Each connection's `ClientContext` now carries `viewing`. The **viewed-agent
  set** is the set of agent names any connection currently reports as `viewing`
  (a blurred client reports `null`, so its entry drops out).
- Replace the single `last_online_at: Option<Instant>` + `pending_return: bool`
  with per-agent maps:
  - `last_viewed_at: HashMap<String, Instant>`
  - `pending: HashSet<String>`
- `record()` returns `Option<String>` — the agent name that just **started** a
  return — instead of `bool`. An agent starts a return when it enters the viewed
  set, is not already pending, and either has no `last_viewed_at` or was last
  viewed ≥ `PRESENCE_NOTIFY_DEBOUNCE` ago. The resync frame never starts a
  return.
- `confirm_return(agent, now)` replaces `confirm_return(now)`: it consumes
  `agent` from `pending` and returns whether `agent` is still in the viewed set.
  When it is, it stamps `last_viewed_at[agent] = now` and returns the still-
  viewing `ClientKind` (for the notification's surface label); when the user has
  navigated away, it returns `None` and leaves `last_viewed_at[agent]` at the
  pre-glance value so a later genuine open still fires.
- The `any_focused` watch is untouched: still computed from `focused` across all
  connections, independent of `viewing`.

Per-agent glance handling mirrors today: a `viewing` that enters and leaves the
set inside the settle window is a glance and consumes nothing; a re-open while
that agent is already `pending` schedules nothing new.

### 3. Settle + drop (`vestad/src/sync/handler.rs`, `vestad/src/serve.rs`)

- When `record()` yields `Some(agent)`, spawn `settle_and_notify(state, agent)`.
  After `PRESENCE_NOTIFY_DELAY`, if `confirm_return(agent)` yields a
  `ClientKind` and `presence_notification_target(agent)` holds (the agent serves
  its tap now and its `presence_notifications` toggle is enabled), drop a
  `user-presence` notification into **that one agent**.
- Replace the fan-out helper `presence_notification_agents()` with the
  single-agent `presence_notification_target(agent)`
  (`serves_ws && presence_notifications_enabled`). Gating on the live tap is what
  keeps a mid-restart opt-out (whose toggle reads as the enabled default) from
  being notified against its preference.
- `drop_presence_notification(docker, agent, client)` is unchanged in shape; it
  still carries `ClientKind` for the surface label.
- Notification copy becomes agent-specific:
  `"the user just opened your page on {client} and is here now."` The payload's
  `source`, `type`, and `interrupt: false` are unchanged, so the agent-side
  notification contract does not move.

### 4. Clients

- Web `PresenceReporter` (`apps/web/src/providers/PresenceReporter/`) reports
  `viewing` from the current `/agent/{name}` route: the agent name when the
  window is focused and on an agent route, `null` otherwise. It folds `viewing`
  into the same `client_context` frame the socket already emits, re-emitting
  whenever the route or focus changes.
- Mobile reports its currently-open agent the same way through the controller's
  presence path.
- `@vesta/core` `socket.ts` / `frames.ts` carry `viewing` on the frame and track
  a `lastViewing` alongside `lastFocused`, emitting when either changes and
  replaying both on reconnect as a resync.

## Testing

- `presence.rs` unit tests, re-keyed per agent: per-agent debounce fires
  independently; opening agent A does not notify agent B; a glance on A consumes
  nothing; a resync frame never starts a return; two agents can be pending at
  once; navigating away inside the settle window sends nothing.
- `serve.rs` payload test: the message names the client surface and the copy is
  the per-page wording; `source`/`type`/`interrupt` unchanged.
- Handler-level: `record() -> Some(agent)` spawns a settle that drops into only
  that agent; a disabled `presence_notifications` toggle on that agent suppresses
  the drop.
- `@vesta/core` `socket.test.ts` / `parse` tests: `viewing` round-trips on the
  frame, replays as resync on reconnect, and an absent `viewing` is ignored
  (ignore-unknown pin stays green).
- Contract fixture (`sync-protocol.json`) regenerated if the frame example
  changes; confirm the regen does not reshape a field shipped clients read.

## Blast radius

- No agent-side code change and no change to the notification file's
  `source`/`type`/`interrupt`, so **no migration** is needed.
- `MIN_SUPPORTED_CLIENT_VERSION` does not move (additive, ignore-unknown).
- Behavior change only: an old client that never reports `viewing` stops
  producing presence notifications rather than fanning out globally. Acceptable
  and the safe direction.

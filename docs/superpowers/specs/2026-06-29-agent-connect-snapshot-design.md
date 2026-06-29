# Agent connect snapshot — unified "hey, here's whatsup" handshake event

**Date:** 2026-06-29
**Area:** `agent/core/` (api.py, events.py, loops.py) + `apps/web/` (AgentSocketProvider, NotificationsCard)
**Status:** Design — awaiting review
**Supersedes:** the seed mechanism of the already-merged live-notifications work (the
`notification_cleared`-in-history + `/notifications/pending` approaches). Builds on
[2026-06-29-chat-shadcn-primitives-design.md] only incidentally (same branch).

## Problem

The notifications settings view should reflect, live, which received notifications are still
**pending** (received but not yet processed by the agent). The first cut derived pending purely
from the event log (`notification` arrivals minus `notification_cleared` events). A code review
found this breaks down:

1. **No backfill** — `notification_cleared` is new, so every notification processed before it
   shipped has no clear in the log and renders permanently pending.
2. **Pagination budget** — folding clears into the paginated notifications channel makes them
   spend the same page budget as arrivals, so pages show few rows and "load older" can stall.
3. **Reconnect** — the resync reloaded only page 1, discarding loaded older pages.

Root realization: **pending is current *disk* state — a tiny set (only the unprocessed few) —
not something to reconstruct from an unbounded event log.** It wants a small authoritative
*seed* plus live deltas, not log archaeology.

We also don't want to pile this onto vestad's `/status` readiness probe: vestad polls `/status`
every 3s purely for Alive/SettingUp gating and ignores everything else, so seed data there is
globbed-and-discarded 20×/min and conflates two audiences.

## Design

The agent already pushes connect-time seed state on a successful WS handshake — the `history`
event (recent chat + activity `state` + cursor), sent once, directly to the connecting client.
Generalize that into a single extensible **`snapshot`** event.

### The event

Sent once per successful WS handshake, directly to that client via `ws.send_json` — **not**
through the event bus, so it is never persisted to `events.db` nor broadcast to other clients.

```jsonc
{
  "type": "snapshot",
  "state": "idle" | "thinking",          // agent-wide activity at connect
  "chat": {
    "events": [ /* recent app-chat events */ ],
    "cursor": 1234 | null                 // load-older pagination cursor
  },
  "notifications": {
    "pending": ["<notif_id>", "..."]      // notification file stems still on disk
  }
}
```

**Field convention.** Each top-level key (except the agent-wide scalar `state`) is a *domain
object* — `chat`, `notifications`, … — so we extend within a domain
(`notifications.unread`, `chat.unseen`) or add a new domain (`voice: {...}`) without disturbing
existing readers. Readers treat an absent domain as "nothing to seed" (defensive reads).

### What it replaces / leaves alone

- **Replaces** the connect-time `history` event. `chat.events` / `chat.cursor` / `state` carry
  exactly what `history` did.
- **Unchanged:** the live event stream (`status`, `chat`, `tool_*`, `notification`,
  `notification_cleared`) still flows over the bus after the handshake; the REST `/history`
  endpoint still serves *load-older* pagination; `/status` stays vestad's lean readiness probe.
- `notification_cleared` becomes a **live broadcast-only delta** (not persisted, not in any
  history channel). The earlier `_NOTIFICATION_CONDITION` channel-widening is reverted, and the
  earlier `/notifications/pending` endpoint stays removed (its glob now feeds `snapshot`).

### Pending model (frontend)

`pendingSet = snapshot.notifications.pending  ∪  live notification arrivals  −  live notification_cleared`

- Seed from the snapshot on connect (authoritative disk state — small).
- A live `notification` arrival adds its `notif_id` (its file is on disk → pending).
- A live `notification_cleared` removes its `notif_id`.
- A row renders pending iff `pendingSet.has(notif_id)`.
- **Reconnect re-sends the snapshot**, which re-seeds `pendingSet` for free — no special resync.

## Backend changes (`agent/core`)

- `events.py`: add `SnapshotEvent` with typed `state` / `chat` / `notifications` sub-shapes;
  remove `HistoryEvent` from the union.
- `api.py` `_ws_handler`: on connect, build + send the snapshot. `chat` via
  `event_bus.recent("app-chat")`; `notifications.pending` via a notifications-dir glob; `state`
  from the bus — **all off-loop** (`asyncio.to_thread`) so a large scan never freezes the agent.
- `skip_history=1` (NotificationProvider taps): omit `chat.events` (the heavy part); still send
  `state` + `notifications` (both cheap). (Param rename to `lite`/`no_chat` is a later nicety,
  not in scope.)
- `events.py` `emit()`: skip persisting `notification_cleared` (broadcast-only), alongside the
  existing `status` skip. Revert `_NOTIFICATION_CONDITION` to `'notification'` only.
- `loops.py`: unchanged — still emits `notification_cleared` on file delete (now broadcast-only).

## Frontend changes (`apps/web`)

- `types.ts`: `snapshot` variant (replaces `history`); keep `notification_cleared`.
- `providers/AgentSocketProvider/use-agent-socket.ts`: handle `snapshot` → seed `messages` =
  `chat.events`, cursor, `historyLoaded`, `agentState` = `state`, and a new `pendingNotifications`
  = `notifications.pending`; expose `pendingNotifications` on the context value.
- `components/AgentSettings/NotificationsCard/`: replace the cleared-from-log logic with the
  `pendingSet` model above; `getNotificationHistory` reverts to `{ notifications, cursor }`.

## CLI changes (`cli/`)

The `vesta` CLI is a first-class consumer of the same agent WS (`/agents/{name}/ws`), not just
the web app. It parses events directly (`client.rs`):

- live `chat` events → agent lines (unchanged),
- on connect, the `history` event's flat `events` array → renders the conversation backlog
  (`client.rs:857-873`, reads `msg["events"]`).

So the CLI must move to the `snapshot` event, reading `msg["chat"]["events"]` (nested) for its
connect-history rendering. It reads **only the `chat` domain** — it has no notifications/settings
view (only notification-*policy* commands over REST), so it ignores `state`/`notifications`.
This is the payoff of the domain-object shape: one event, each client reads its own domains.

Parity here means the CLI keeps working over the shared event — not that it gains the pending
view (that stays web-only). Its `history` branch is replaced by a `snapshot` branch reading
`snapshot.chat.events`.

## vestad changes (`vestad/`)

vestad is a third consumer of the connect event. Its internal activity listener
(`agent_status.rs:42-45`) matches `msg_type == "status" || msg_type == "history"` and reads
top-level `parsed["state"]` to track idle/thinking. Swap `"history"` → `"snapshot"` in that
match; because `state` stays **top-level** in the snapshot, the existing `state` read is
unchanged. It ignores `chat`/`notifications`.

The listener currently connects without `skip_history`, so it already pulls (and discards) the
chat backlog; with the snapshot it can opt into the lite form (`skip_history=1` → no
`chat.events`) to stop pulling history it never reads — an optional optimization, not required
for correctness.

## Rollout — hard cut, no back-compat

`history` is replaced by `snapshot` outright; no transitional dual-path. **Assumption: all
surfaces ship in version sync** — agent, vestad, CLI, and the web (served by vestad and bundled
in the apps) are always on the same release. This holds by construction for agent/vestad/cli
(agent code is embedded in the vestad binary via `agent_code::ensure_agent_code` and the crate
versions are release-synced) and is assumed for the bundled apps. So no client ever meets a
mismatched agent, and the event can change in one shot across all four surfaces.

## Verification

- Backend: `_ws_handler` sends a `snapshot` with correct `chat`/`state`/`notifications.pending`
  (test against a fake notifications dir + seeded bus); `notification_cleared` is broadcast but
  not persisted (subscribe + assert, and assert absent from the notifications channel);
  `loops.py` still emits the clear. `./check.sh agent`.
- Frontend: `snapshot` seeds chat + pending; a live arrival marks pending; a live
  `notification_cleared` clears it; reconnect re-seeds. `./check.sh web`.

## Out of scope

- The other code-review cleanups (#4 FilesTab divider, #5 dup projection, #6 double history
  fetch, #7 per-event rescans, #8 dead `sendAgentEvent`, #9 dep-bump isolation, #10 stray
  lockfile) — tracked separately as a simplify pass.
- Adding more snapshot domains (provider/model, version) — the shape allows it; not v1.

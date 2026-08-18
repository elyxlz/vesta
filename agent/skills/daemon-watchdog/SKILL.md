---
name: daemon-watchdog
description: Watches this box's daemons from outside the agent loop and notifies only when one is down. Requires daemon.
---

# Daemon Watchdog

A plain loop in its own process. Every `WATCHDOG_INTERVAL_SECS` (default 120) it asks every daemon in
`~/agent/skills/restart/daemons.sh` for its status, restarts anything that is down, and writes a
notification only when something was actually wrong. A healthy box produces nothing and wakes nobody.

## Why it exists

Waking the whole agent is the expensive way to run a cheap check. A tick whose entire output is
"green, holding" still re-reads the whole context, so the floor cost of asking "is everything up?"
from inside the agent loop is the price of existing for a turn, and it is paid every time. The lever
is not "do less inside a tick", it is "did the tick need to run at all". Liveness has to keep
running, so it lives out here instead.

The deaths ledger (`~/agent/data/daemon-deaths.tsv`) exists for the death nobody restarts. Counting
a daemon's starts can only ever rule out death-AND-restart cycles: a daemon that dies and is never
brought back adds no start, writes nothing to its own log, and leaves no trace anywhere, so a start
count answers a narrower question than the claim it gets used for. The ledger records the death time
bounded by the sweep interval, the last time the daemon was seen alive, and therefore the uptime
that died with it. Without it that class of death is unobservable.

## Commands

```bash
daemon-watchdog daemon start|stop|restart|status   # lifecycle; start returns once a pass has run
daemon-watchdog check                              # one pass, printed; exit 1 if anything needs hands
```

`daemon status` reports `last_pass`, the timestamp of the most recent sweep. That field is the whole
trust model: see below.

## What it does when a daemon is down

It restarts it, then says so. A start is idempotent and is exactly what the `restart` skill does, so
restarting is not a side quest; a watchdog that reports a dead daemon while leaving it dead has
turned an outage into an outage plus a notification.

The notification carries which happened, because they are different situations:

- **Down, restart worked**: non-interrupting. Worth knowing it died on its own, not worth waking for.
- **Down, restart failed**: interrupting. Nothing else will report it, and if it is a messaging
  daemon the user cannot reach the agent at all.
- **Still down on a later pass**: throttled to `WATCHDOG_THROTTLE_SECS` (default 6h), so an open
  problem keeps nagging without becoming noise.
- **Recovered**: the state entry is deleted, so the nagging stops on its own and a later death
  notifies again rather than staying muted.
- **Unmeasurable** (no status verb, non-JSON answer): reported in `check` output, never restarted.
  An unmeasured daemon read as down produces a restart loop against something that was never broken.

## The trust model, which is the point

**A watchdog that dies looks exactly like a quiet night.** No notifications either way. That is the
same shape as a forecaster that cannot speak and a guard nothing invokes, both of which this box has
shipped and had to catch later. So every pass stamps `~/agent/data/daemon-watchdog.beat` whether or
not anything was wrong, and `reality_check.sh` REDs when that stamp goes stale.

Silence from this thing is only worth trusting because something else is proving it is still alive.
Never read "no watchdog notifications" as "the daemons are fine" without checking `last_pass`.

## Testing it

`/tmp` scratch, never a real daemon: the suite stands up fake `<name> daemon status|start` commands
on `PATH` and points the watchdog at a synthetic `daemons.sh` via `WATCHDOG_LIST`,
`WATCHDOG_NOTIFY_DIR`, `WATCHDOG_STATE` and `WATCHDOG_HEARTBEAT`. Do not kill a real daemon to test
this. A monitor that can only be tested by breaking production gets tested once, optimistically, and
its failure path ships unproven.

The suite must always keep a control case that asserts a HEALTHY daemon produces no notification.
Without it, "it fired on the broken one" is equally consistent with a watchdog that always fires.

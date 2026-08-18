---
name: daemon-watchdog
description: Watches this box's daemons from outside the agent loop and notifies only when one is down. Requires daemon.
---

# Daemon Watchdog

A plain loop in its own process. Every `WATCHDOG_INTERVAL_SECS` (default 120) it asks every daemon in
`~/agent/skills/restart/daemons.sh` for its status, records any death, and writes a
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

It records the death, writes a notification, and stops. **It restarts nothing, deliberately.**

The agent stays in control of its own box. A dead daemon is reported to the one entity that can
reason about the cause, and that entity decides what to do. Restarting first would replace the state
the cause is visible in with a working daemon and no evidence, and for a death the daemon could not
report itself, an OOM kill or a SIGKILL, that state is the only evidence there will ever be.

The notification carries which situation it is, because they are not the same:

- **Down**: interrupting. Nothing else will report it, nothing is going to fix it on its own, and if
  it is a messaging daemon the user cannot reach the agent at all.
- **Still down on a later pass**: throttled to `WATCHDOG_THROTTLE_SECS` (default 6h), so an open
  problem keeps nagging without becoming noise.
- **Died repeatedly inside the window**: its own notification type and its own throttle, so it is
  not silenced by the single-death rule. This counts deaths, not restart cycles: it says something
  is killing the daemon, never that restarts are holding it up.
- **Recovered**: the state entry is deleted, so the nagging stops on its own and a later death
  notifies again rather than staying muted.
- **Unmeasurable** (no status verb, a command that cannot be run, a hung status): reported in
  `check` output and never called down. A daemon that cannot be ASKED is not a daemon that is
  down, and collapsing the two sends the agent hunting a fault that may not exist. When *every*
  daemon is unmeasurable that is one cause rather than many, and it says so once under its own type.
- **Running but absent from `daemons.sh`**: read from the pidfile store rather than the list, so the
  expected set does not come from the file being audited. Such a daemon works now and is gone after
  the next restart. A daemon retired on purpose is stopped as well as unlisted, so it stays quiet.

## Testing it

`/tmp` scratch, never a real daemon: the suite stands up fake `<name> daemon status|start` commands
on `PATH` and points the watchdog at a synthetic `daemons.sh` via `WATCHDOG_LIST`,
`WATCHDOG_NOTIFY_DIR`, `WATCHDOG_STATE` and `WATCHDOG_HEARTBEAT`. Do not kill a real daemon to test
this. A monitor that can only be tested by breaking production gets tested once, optimistically, and
its failure path ships unproven.

The suite must always keep a control case that asserts a HEALTHY daemon produces no notification.
Without it, "it fired on the broken one" is equally consistent with a watchdog that always fires.

---
name: tasks
description: Tasks, to-dos, deadlines, due dates; create, track, and manage. Requires daemon.
---

# Tasks (CLI: tasks)

One CLI, one daemon, one SQLite DB. A task is something that needs doing, optionally with a due date. The daemon does the tracking for you: it warns you before a due date, forces a decision at the due time, and sends a daily digest of anything overdue or stale. Your job is to always resolve those notifications with one of the commands below, never to ignore them.

## Tasks

```bash
tasks create "Submit report" --priority high --in-hours 4
tasks create "Meeting prep" --at "2026-12-01T10:00:00" --tz "Europe/London"
tasks list                        # pending tasks, overdue first
tasks done <id>                   # mark completed
tasks postpone <id> --in-days 2   # new due date, measured from now
tasks search "report"
tasks get <id>
tasks update <id> --subject "..." --priority low --status pending
tasks update <id> --clear-due     # remove the due date (silences its checkpoints)
tasks delete <id>                 # remove the task
```

- Due date: `--in-minutes/--in-hours/--in-days` (relative) or `--at` + `--tz` (absolute, both required), the same time flags every command in this skill takes. `--priority` low/normal/high. `--initial-metadata "..."` attaches notes.
- Keep the subject under ~100 characters: it is the one field `tasks list`, the digest, and the app show, so a paragraph there is unreadable everywhere. Detail and running state go in metadata (`--initial-metadata` on create, or edit the task's `metadata_path` file). A longer subject still saves, with a warning.
- `postpone` also takes `--in-minutes/--in-hours` or `--at` + `--tz`, and works on a task with no due date (gives it one).
- `update --clear-due` removes a due date; every other due flag can only move one. The pre-due checkpoints are computed from `due_date`, so clearing the date is the one way to silence them. Reach for it when a date was set by mistake or by a bulk `postpone` over a backlog.
- `tasks get <id> --field status` prints just that field (repeat `--field` for several, tab-separated). Valid fields: id, subject, status, priority, due_date, created_at, completed_at, metadata_path, metadata. Prefer this over reading the metadata file when you need one value.
- `list`/`search` print compact tables (`--show-completed` to include completed); add `--json` or `--json-pretty` for JSON.
- A task's status is `pending`, `in_progress`, or `completed`. `tasks done <id>` and `tasks update <id> --status completed` both close it. `tasks update <id> --status in_progress` marks a task started: it stays open, so it still shows in `tasks list` and still fires its due-date checkpoints.
- To nudge yourself about a task (for example one blocked on someone else), set a reminder with the `reminders` skill (`reminders create "..."`) whose message names the task and its metadata file. The task carries the state; the reminder is only the nudge.

## What the daemon does on its own

- **Spaced pre-due checkpoints**: for each due date, notifications at widening lead times before it (15 minutes, 1 hour, 1 day, 1 week, then doubling from 2 weeks). They are computed from the due date, never stored: a retitle or postpone needs no bookkeeping, and after daemon downtime one catch-up fires instead of a backlog.
- **A decision fire at the due time.** When it arrives you must pick one, immediately: do the task and `tasks done <id>`, or `tasks postpone <id> --in-days N`, or tell the user you are dropping it and `tasks delete <id>`. Marking a task done without doing it is never an option.
- **Daily digest** (`type=task_digest`): one notification per day listing every overdue task and every task pending 2+ weeks with no due date, with the same three choices. It returns every day until the list is empty; work it down, don't acknowledge it.
- **Parking a deliberately undated task**: `tasks update <id> --backburner` (undo with `--no-backburner`). Use it when the undated state is a decision you can defend, because someone else drives the task or it is a genuine someday. It defers the nag, never the task: a parked task stays pending and still appears in `tasks list` marked `[parked]`, it just stops being listed as stale. Parked and deadlined cannot coexist, so parking a dated task drops its due date, and giving a parked task a real due date unparks it. **A task you are simply avoiding should be dropped or dated, not parked, and never invent a deadline to buy silence.**
- Completing or deleting a task silences its checkpoints (like clearing the date).

## Data

DB `~/.tasks/tasks.db`; metadata `~/.tasks/metadata/<id>.md`; logs `~/.tasks/logs/daemon.log`; startup log
`~/agent/logs/tasks.log`; pid and port records `~/agent/data/daemons/tasks.pid` and `tasks.port`.

## Setup

```bash
uv tool install --editable ~/agent/skills/tasks/cli
```

## Background Daemon

One daemon handles task due-date monitoring and the daily digest.

`tasks daemon start|stop|restart|status`. Start is idempotent (a live daemon is a no-op) and owns
the port registration with vestad; stop is the deliberate shutdown, so it does not fire the
`daemon_died` notification every other exit fires. Manage the daemon through these commands, never
by launching `tasks serve` yourself.

So the daemon survives restarts, read the `restart` skill and add this line to your restart daemons:
```
tasks daemon start
```

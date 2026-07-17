---
name: tasks
description: Tasks, to-dos, reminders, time-based alerts; create and manage. Requires daemon.
---

# Tasks + Reminders (CLI: tasks)

One CLI, one daemon, one SQLite DB. Tasks are what needs doing; reminders are nudges about when. The daemon does the tracking for you: it reminds you before a due date, forces a decision at the due time, and sends a daily digest of anything overdue or stale. Your job is to always resolve those notifications with one of the commands below, never to ignore them.

## Tasks

```bash
tasks add "Submit report" --priority high --due-in-hours 4
tasks add "Meeting prep" --due-datetime "2026-12-01T10:00:00" --timezone "Europe/London"
tasks list                        # pending tasks, overdue first
tasks done <id>                   # mark done
tasks postpone <id> --in-days 2   # new due date, measured from now
tasks search "report"
tasks get <id>
tasks update <id> --title "..." --priority low --status pending
tasks delete <id>                 # cascades to linked reminders
```

- Due date: `--due-in-minutes/--due-in-hours/--due-in-days` (relative) or `--due-datetime` + `--timezone` (absolute, both required). `--priority` low/normal/high. `--initial-metadata "..."` attaches notes.
- `postpone` also takes `--in-minutes/--in-hours` or `--at` + `--tz`, and works on a task with no due date (gives it one).
- `tasks get <id> --field status` prints just that field (repeat `--field` for several, tab-separated). Valid fields: id, title, status, priority, due_date, created_at, completed_at, metadata_path, metadata. Prefer this over reading the metadata file when you need one value.
- `list`/`search` print compact tables (`--show-completed` to include done); add `--json` or `--json-pretty` for JSON.

## Reminders

The message is the first argument to `tasks remind`; there is no create/add/set subcommand:

```bash
tasks remind "Call mom" --in-minutes 30
tasks remind "Meeting" --at "2026-12-01T10:00:00" --tz "Europe/London"
tasks remind "Check progress" --task <id> --in-hours 1
tasks remind "Standup" --recurring daily --at "2026-12-01T09:30:00" --tz "America/New_York"
tasks remind "Evening check-in" --recurring daily --at "2026-12-01T21:30:00" --tz "Europe/Rome" --fuzz-minutes 75
tasks remind "Weekdays 9am" --cron "0 9 * * 1-5" --tz "America/New_York"
tasks remind list [--task <id>]
tasks remind snooze <id> --in-hours 4    # push a one-shot back; works on already-fired ones too
tasks remind update <id> --message "..."
tasks remind delete <id>
```

- One-shot: `--in-minutes/--in-hours/--in-days` or `--at` + `--tz`. Always use the user's IANA timezone from MEMORY.md, never UTC.
- Recurring: `--recurring hourly|daily|weekly|monthly|yearly` (all but hourly need `--at` + `--tz`), or `--cron "min hour dom month dow"` + `--tz` for anything else (standard cron: 0/7 = Sunday, ranges/lists/steps/names supported). Both keep their wall-clock time across DST.
- `--fuzz-minutes N` (recurring/cron only): each fire lands at a varying point within N minutes either side of the nominal time, so a routine feels natural instead of firing at 09:30:00 sharp every day. Translate vague times yourself: "late evening" is roughly `--at ...T21:30:00 --fuzz-minutes 75`. Use fuzz for human-facing rhythms, never for deadlines; it must fit within half the gap between fires.
- A recurring reminder's message is an instruction: when it fires, act on it. Recurring reminders double as scheduled automations.

## What the daemon does on its own

- **Spaced pre-due reminders**: for each due date, checkpoints that halve the remaining time (a task due in 6 months pings at about 3 months, 6 weeks, 3 weeks), then 1 week, 1 day, 1 hour, and 15 minutes before due.
- **A decision fire at the due time.** When it arrives you must pick one, immediately: do the task and `tasks done <id>`, or `tasks postpone <id> --in-days N`, or tell the user you are dropping it and `tasks delete <id>`. Marking a task done without doing it is never an option.
- **Daily digest** (`type=task_digest`): one notification per day listing every overdue task and every task pending 2+ weeks with no due date, with the same three choices. It returns every day until the list is empty; work it down, don't acknowledge it.
- **Missed one-shots**: reminders that should have fired while the daemon was down are sent on restart marked `missed`; missed recurring fires are skipped.
- Completing or deleting a task cleans up its auto reminders; postponing rebuilds them for the new date.

## Data

DB `~/.tasks/tasks.db`; metadata `~/.tasks/metadata/<id>.md`; logs `~/.tasks/logs/daemon.log`; PID `~/.tasks/serve.pid`.

## Setup

```bash
uv tool install --editable ~/agent/skills/tasks/cli
```

## Background Daemon

One daemon handles everything: task due-date monitoring, reminder scheduling, and the daily digest. `--notifications-dir` defaults to `~/agent/notifications`; pass it only to override. Register with vestad to get a port (see [vestad](../vestad/SKILL.md)) and add this startup command to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:
```
running tasks || { PORT=$(~/agent/skills/vestad/scripts/register-service tasks) && screen -dmS tasks tasks serve --port $PORT; sleep 1; }
```

**Liveness**: `tasks daemon status` (add `-q` for exit-code only: 0 serving, 1 not). It curls the daemon's own HTTP port (recorded in `~/.tasks/serve.port` on start), so it reports whether the daemon is actually serving, not merely that a `screen` session or the sqlite store exists. This is the same `daemon status` check the messaging daemons expose; proactive-check calls it to catch a silently dead daemon.

### Reminder Patterns
[User's common reminder types and preferences]

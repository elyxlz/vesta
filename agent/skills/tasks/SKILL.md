---
name: tasks
description: Tasks, to-dos, reminders, time-based alerts; create and manage. Requires daemon.
---

# Tasks + Reminders (CLI: tasks)

One CLI, one daemon, one SQLite DB. Tasks are what needs doing; reminders are nudges about when. The daemon does the tracking for you: it reminds you before a due date, forces a decision at the due time, and sends a daily digest of anything overdue or stale. Your job is to always resolve those notifications with one of the commands below, never to ignore them.

## Tasks

```bash
tasks create "Submit report" --priority high --due-in-hours 4
tasks create "Meeting prep" --due-datetime "2026-12-01T10:00:00" --timezone "Europe/London"
tasks list                        # pending tasks, overdue first
tasks done <id>                   # mark completed
tasks postpone <id> --in-days 2   # new due date, measured from now
tasks search "report"
tasks get <id>
tasks update <id> --subject "..." --priority low --status pending
tasks update <id> --clear-due     # remove the due date (and its auto reminders)
tasks delete <id>                 # cascades to linked reminders
```

- Due date: `--due-in-minutes/--due-in-hours/--due-in-days` (relative) or `--due-datetime` + `--timezone` (absolute, both required). `--priority` low/normal/high. `--initial-metadata "..."` attaches notes.
- Keep the subject under ~100 characters: it is the one field `tasks list`, the digest, and the app show, so a paragraph there is unreadable everywhere. Detail and running state go in metadata (`--initial-metadata` on create, or edit the task's `metadata_path` file). A longer subject still saves, with a warning.
- `postpone` also takes `--in-minutes/--in-hours` or `--at` + `--tz`, and works on a task with no due date (gives it one).
- `update --clear-due` removes a due date. Every other due flag can only move a date, so without this a due date is a one-way door: auto reminders are regenerated from `due_date`, so deleting them by hand does not stick. Reach for it when a date was set by mistake or by a bulk `postpone` over a backlog, since a backburner item with a due date fires a whole reminder cascade it never earned.
- `tasks get <id> --field status` prints just that field (repeat `--field` for several, tab-separated). Valid fields: id, subject, status, priority, due_date, created_at, completed_at, metadata_path, metadata. Prefer this over reading the metadata file when you need one value.
- `list`/`search` print compact tables (`--show-completed` to include completed); add `--json` or `--json-pretty` for JSON.
- A task's status is `pending`, `in_progress`, or `completed`. `tasks done <id>` and `tasks update <id> --status completed` both close it. `tasks update <id> --status in_progress` marks a task started: it stays open, so it still shows in `tasks list` and still fires its due-date reminders.

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
tasks remind snooze <id> --at "2026-12-01T17:00:00" --tz "Europe/London"   # move it to a SPECIFIC time
tasks remind update <id> --message "..."
tasks remind delete <id>
```

- One-shot: `--in-minutes/--in-hours/--in-days` or `--at` + `--tz`. Always use the user's IANA timezone from MEMORY.md, never UTC.
- Recurring: `--recurring hourly|daily|weekly|monthly|yearly` (all but hourly need `--at` + `--tz`), or `--cron "min hour dom month dow"` + `--tz` for anything else (standard cron: 0/7 = Sunday, ranges/lists/steps/names supported). Both keep their wall-clock time across DST.
- `--fuzz-minutes N` (recurring/cron only): each fire lands at a varying point within N minutes either side of the nominal time, so a routine feels natural instead of firing at 09:30:00 sharp every day. Translate vague times yourself: "late evening" is roughly `--at ...T21:30:00 --fuzz-minutes 75`. Use fuzz for human-facing rhythms, never for deadlines; it must fit within half the gap between fires.
- A recurring reminder's message is an instruction: when it fires, act on it. Recurring reminders double as scheduled automations.
- **`snooze --in-minutes/--in-hours/--in-days` counts from NOW, not from the reminder's own fire time.** Asking for a 7 hour shift on a reminder four days out moves it to this evening, not to seven hours after it was due. To move a reminder to a specific later moment, use **`snooze <id> --at <iso> --tz <tz>`**, which is supported but is not shown in the usage line or in `--help`. Prefer that over delete-and-recreate: deleting changes the id, so every note, file and message that referenced the old id silently becomes wrong.
- **`remind update` takes ownership of a reminder.** Rewriting the message of an auto-generated pre-due reminder makes it yours: it stops being regenerated by `postpone` or a due-date change, loses its `*` marker, and is relabelled from `auto: ...` to a plain one-off. That is the way to keep one hand-written checkpoint on a task that is blocked on someone else, instead of a pile of pre-fires reciting a task title you cannot act on. Closing the task with `tasks done` clears every reminder tied to it, owned ones included, so a finished task never keeps firing.

### When a reminder needs more than a sentence: staged files

A reminder whose job carries real material (a draft, a verified list, a decision and its reasons) should keep that material in a file and name the file in its message. The reminder is the trigger; the file is the answer. That split works, and it rots in four specific ways, each of which has a cheap fix. Note that these instructions arrive with your own authority and a deadline attached, so they are followed harder than anything else you read, which is exactly why stale ones are dangerous.

- **State that the file wins.** Put a line like "the file overrides this text" in the reminder message. Otherwise the two drift and you have no rule for which to believe when they disagree.
- **Newest answer at the TOP, with its date.** The common failure is appending a new finding below an instruction it invalidates: when the reminder fires you open the file and the first thing you read is the superseded plan. Open every staged file with a dated current-answer block, and edit the old decision rather than burying it. If a superseded block is worth keeping as a trail, mark it superseded in place.
- **Never duplicate schedule data between the two.** Ids, dates and times copied from `tasks remind list` into a file (or from a file into a reminder message) go stale the first time you edit one of them, and a confident wrong date is worse than no date. Keep the schedule in the reminder and let the file hold judgement and content.
- **No relative dates in a staged file.** "Tomorrow", "this week" and "after the trip" are true when written and false the next morning, and nothing flags them. Write absolute dates, the same rule that applies to long-term memory.

Same care when the reminder is one you will act on rather than send: a fired reminder is read in a hurry, which is when a stale top-of-file instruction does its damage.

## What the daemon does on its own

- **Spaced pre-due reminders**: for each due date, checkpoints that halve the remaining time (a task due in 6 months pings at about 3 months, 6 weeks, 3 weeks), then 1 week, 1 day, 1 hour, and 15 minutes before due.
- **A decision fire at the due time.** When it arrives you must pick one, immediately: do the task and `tasks done <id>`, or `tasks postpone <id> --in-days N`, or tell the user you are dropping it and `tasks delete <id>`. Marking a task done without doing it is never an option.
- **Daily digest** (`type=task_digest`): one notification per day listing every overdue task and every task pending 2+ weeks with no due date, with the same three choices. It returns every day until the list is empty; work it down, don't acknowledge it.
- **Parking a deliberately undated task**: `tasks update <id> --backburner` (undo with `--no-backburner`). Use it when the undated state is a decision you can defend, because someone else drives the task or it is a genuine someday. It defers the nag, never the task: a parked task stays pending and still appears in `tasks list` marked `[parked]`, it just stops being listed as stale. Parked and deadlined cannot coexist, so parking a dated task drops its due date and its auto reminders, and giving a parked task a real due date unparks it. **A task you are simply avoiding should be dropped or dated, not parked, and never invent a deadline to buy silence.**
- **Missed one-shots**: reminders that should have fired while the daemon was down are sent on restart marked `missed`; missed recurring fires are skipped.
- Completing or deleting a task cleans up its auto reminders; postponing rebuilds them for the new date.

## Data

DB `~/.tasks/tasks.db`; metadata `~/.tasks/metadata/<id>.md`; logs `~/.tasks/logs/daemon.log`; startup log
`~/agent/logs/tasks.log`; pid and port records `~/agent/data/daemons/tasks.pid` and `tasks.port`.

## Setup

```bash
uv tool install --editable ~/agent/skills/tasks/cli
```

## Background Daemon

One daemon handles everything: task due-date monitoring, reminder scheduling, and the daily digest.

`tasks daemon start|stop|restart|status`. Start is idempotent (a live daemon is a no-op) and owns
the port registration with vestad; stop is the deliberate shutdown, so it does not fire the
`daemon_died` notification every other exit fires. Manage the daemon through these commands, never
by launching `tasks serve` yourself.

So the daemon survives restarts, read the `restart` skill and add this line to your restart daemons:
```
tasks daemon start
```

### Reminder Patterns
[User's common reminder types and preferences]

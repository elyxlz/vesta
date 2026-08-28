---
name: reminders
description: Time-based nudges and alarms; remind the user or yourself to do something at a set time or on a repeating schedule (one-shot, daily/weekly/monthly/cron). Not for tracked to-dos, which are the tasks skill. Requires daemon.
---

# Reminders (CLI: reminders)

A reminder is a standalone nudge that fires at a time or on a schedule: "take meds at 08:00", "stand-up every weekday at 09:30". The daemon holds the schedule and writes a notification when a reminder fires. The message is an instruction to act on when it arrives.

`reminders create` sets one; the message is its first argument.

```bash
reminders create "Call mom" --in-minutes 30
reminders create "Take meds" --at "2026-12-01T08:00:00"
reminders create "Stand-up" --recurring daily --at "09:30"   # daily takes a bare time
reminders create "Contraceptive" --recurring daily --at "23:00"
reminders create "Evening check-in" --recurring daily --at "21:30" --fuzz-minutes 75
reminders create "Weekdays 9am" --cron "0 9 * * 1-5"
reminders create "Market open" --recurring daily --at "09:30" --tz "America/New_York"   # --tz pins the schedule to that zone
reminders list [--show-completed] [--show-deleted]   # fired and deleted ones stay hidden until asked for
reminders get <id>                             # one reminder as JSON; resolves deleted ones too
reminders get <id> --field next_run            # just that value
reminders snooze <id> --in-hours 4             # fire 4h from NOW; works on already-fired ones too
reminders snooze <id> --at "2026-12-01T17:00:00"   # move it to a specific time
reminders update <id> --message "..."
reminders update <id> --tz "America/New_York"   # repoint a recurring schedule, same id
reminders update <id> --unpin-tz                # back to the agent's own timezone
reminders delete <id>
```

- Times are in the agent's own timezone. Pass `--tz` (an IANA name) only to pin a schedule to a different zone, such as a market or a flight.
- One-shot: `--in-minutes/--in-hours/--in-days` (relative) or `--at` (absolute; add `--tz` for a different zone). A one-shot is a fixed instant: a later timezone change does not move it.
- Recurring: `--recurring hourly|daily|weekly|monthly|yearly` (all but hourly need `--at`; daily accepts a bare time like `--at "21:30"`, the others take their weekday or day from the date), or `--cron "min hour dom month dow"` for anything else (standard cron: 0/7 = Sunday, ranges/lists/steps/names supported). Both keep their wall-clock time across DST. An unpinned recurring reminder follows the agent's timezone: a timezone change applies to it after the next restart. A `--tz`-pinned one stays in its zone, and `reminders list` names the zone on exactly those rows.
- `--fuzz-minutes N` (recurring/cron only): each fire lands at a varying point within N minutes either side of the nominal time, so a routine feels natural instead of firing at 09:30:00 sharp every day. Translate vague times yourself: "late evening" is roughly `--at "21:30:00" --fuzz-minutes 75`. Use fuzz for human-facing rhythms, never for a hard deadline; it must fit within half the gap between fires.
- A recurring reminder's message is an instruction: when it fires, act on it. Recurring reminders double as scheduled automations.
- Snooze moves one-shot reminders only, fired ones included; a recurring reminder fires again on its own, and the CLI rejects snoozing it. Snooze says when two ways, one per call: `--in-*` counts from now, `--at` names the moment (add `--tz` for a different zone). The result echoes `previous_run` and `next_run`; read them back to confirm the reminder landed where you meant. Prefer snooze over delete-and-recreate: deleting changes the id, so every note, file and message that referenced the old id silently becomes wrong.
- `update` rewrites a reminder in place, under the same id: `--message` for the text, `--tz <zone>` or `--unpin-tz` for a recurring schedule's zone. `--tz` keeps the wall-clock time and reads it in the new zone, `--unpin-tz` drops the pin so the schedule follows the agent's own timezone, and both recompute the next fire and reach the running daemon on its next sync. A one-shot is a fixed instant with no zone to move: use snooze. The rest of a recurring schedule (its time, its days, its fuzz) changes only by delete plus recreate, which changes the id, so fix everything that referenced the old one.
- `get <id> --field <name>` prints just that field (repeat `--field` for several, tab-separated). Valid fields: id, message, schedule, next_run, created_at, status, deleted_at, metadata_path, metadata_content.
- `delete` is a soft delete: the reminder is kept, it never fires again, and it drops off `reminders list`. There is no undelete: `snooze` and `update` refuse a deleted id. `reminders list --show-deleted` brings it back, marked `[deleted]`, so a past id still resolves.
- `list` prints a compact table of the first 50; `--json`/`--json-pretty` list all unless `--limit` is given.

## When a reminder needs more than a sentence: staged files

A reminder whose job carries real material (a draft, a verified list, a decision and its reasons) should keep that material in a file and name the file in its message. The reminder is the trigger; the file is the answer. A reminder always names its OWN file. The split works, and it rots in specific ways, each with a cheap fix.

- **The file wins.** When the reminder text and its file disagree, believe the file. That rule lives here, so the message does not have to carry it: the message was written once, the file is the thing you keep editing.
- **Write the file as dated blocks, newest at the TOP.** Each block opens with a heading like `## 2026-08-15 14:00: <what changed>`. Insert a new block directly under the title, never at the end: the natural motion is to append, and appending sinks the newest answer below a stale plan that then greets every future read. Edit a superseded decision in place, or mark it superseded where it stands.
- **Take the block's timestamp from the clock, never from your head.** Run `date` and paste its output into the heading. The timestamp decides which of two contradicting blocks wins, and a hand-typed time can land in the future, where it beats a later, truer block while looking exactly as reasonable on re-read.
- **Never duplicate schedule data between the two.** Ids, dates and times copied from `reminders list` into a file (or from a file into a reminder message) go stale the first time you edit one of them, and a confident wrong date is worse than no date. Keep the schedule in the reminder and let the file hold judgement and content.
- **No relative dates in a staged file.** "Tomorrow", "this week" and "after the trip" are true when written and false the next morning, and nothing flags them. Write absolute dates, the same rule that applies to long-term memory.

Same care when the reminder is one you will act on rather than send: a fired reminder is read in a hurry, which is when a stale top-of-file instruction does its damage.

To nudge yourself about a task, set a reminder whose message names the task and its metadata file, and delete the reminder with `reminders delete <id>` when you close the task.

## Reminder metadata

A reminder can carry a markdown notes file of its own, the same shape the tasks skill uses:

```
~/.reminders/metadata/<reminder-id>.md
```

The id is the one the CLI prints. Write the file directly; there is no CLI flag for it.

Use it when a reminder needs more than its message can hold. The message says WHERE, the file says WHAT, so the message stays short enough to read as a title wherever it is listed, and the working detail still has somewhere to live. Everything the staged-files section above says (dated blocks newest first, absolute dates, the file wins on a disagreement) applies to this file too.

Prefer a TASK's metadata file when a task already exists, and have the reminder point at the task; reminder metadata is for a reminder that stands alone.

`reminders get <id>`, and `GET /reminders/<id>` on the daemon's HTTP API, returns the file as `metadata_content` and its location as `metadata_path`, with `metadata_content` null when there is no file. `reminders list` leaves both out on purpose: a notes file carries the detail a one-line message cannot hold, so it runs long, and a list returning every one of them would be far heavier than the list itself.

## What the daemon does on its own

- A reminder firing on schedule arrives as a `type=reminder_due` notification. To route reminders with a `notifications` rule, key it on `source=reminders` plus `type=reminder_due` (on-schedule) or `type=reminder_missed` (below).
- **Missed one-shots**: a reminder that should have fired while the daemon was down is sent on restart as a `type=reminder_missed` notification; missed recurring fires are skipped.
- A fired one-shot is marked completed and drops off `reminders list`; `--show-completed` brings it back so a self-chaining reminder can re-read its own body.

## Data

DB `~/.reminders/reminders.db`; metadata `~/.reminders/metadata/<id>.md`; logs `~/.reminders/logs/daemon.log`; startup log `~/agent/logs/reminders.log`;
pid and port records `~/agent/data/daemons/reminders.pid` and `reminders.port`.

## Setup

```bash
uv tool install --editable ~/agent/skills/reminders/cli
```

## Background Daemon

The daemon schedules every reminder and writes the notification when one fires.

`reminders daemon start|stop|restart|status`. Start is idempotent (a live daemon is a no-op) and owns the port
registration with vestad; stop is the deliberate shutdown, so it does not fire the `daemon_died`
notification every other exit fires. Manage the daemon through these commands, never by launching
`reminders serve` yourself.

So the daemon survives restarts, read the `restart` skill and add this line to your restart daemons:
```
reminders daemon start
```

### Reminder Patterns
[User's common reminder types and preferences]

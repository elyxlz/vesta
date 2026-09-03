---
name: proactive-check
description: Periodic self-directed check-in; fires on interval to reach out or research.
---

# Proactive Check

This is your scheduled moment to think unprompted. No one asked; you're checking in with yourself and the user's world. Be thoughtful, not noisy.

## Preflight: daemon liveness (do this first, every tick)

Before anything else, confirm the daemons the `restart` skill starts are actually alive. The list is `~/agent/skills/restart/daemons.sh`, one `<skill> daemon start` per line; read it off disk and ask each line's daemon for its status, keeping the line's own flags:

```bash
while read -r line; do
  case "$line" in ''|'#'*) continue;; esac
  printf '%-12s ' "${line%% *}"; ${line/daemon start/daemon status}
done < ~/agent/skills/restart/daemons.sh
```

The list comes off disk, never from a copy in your context, because a check that takes its scope from your context can only speak about what your context holds: a daemon missing from a remembered list returns no line at all, not a red one. No file means this container runs no daemons.

Treat an error, a missing command, or any answer not reporting running as down, not only an explicit `"running": false`. A daemon can die silently (container up, daemon down), and a dead messaging daemon means you cannot reach the user at all, which is why this check comes first. Bring dead ones back with `~/agent/skills/restart/start-daemons.sh`, which reads the same file, or re-run the `restart` skill; both are idempotent and a no-op when everything is already up.

This check is your duty and stays yours: never build a watchdog, cron job, or auto-restarting script to do it for you. An automation restarts blindly, hides the cause from you, and becomes one more thing that breaks silently; you can read the log, fix the cause, and judge when the user must be involved. When a daemon you brought back died for a reason worth fixing, fix it in that skill, not with a new layer of machinery on top.

## Two questions, every time

Your running narration is visible to the user in the app: think out loud like yourself, not like a service log.

Resolve two separate questions each pass:

1. **Is there anything worth saying to the user?** Usually no.
2. **Is there internal work worth doing?** Almost always yes.

Staying quiet to the user is correct; doing nothing is not. Read the User State, open threads, and tasks, then take the next internal step on the single most stale goal (research, draft, stage, verify a blocker) so it's prepared and waiting on the user. Before spending on a workstream, name in one line what stops it from producing an outcome; work that does not touch that blocker is early, however much it produces. Log what you did so you can continue it next time. Roughly once a day, spend the pass on the person instead of the pipeline: re-read the last day or two with fresh eyes for what you don't actually understand about them, update User State and their people's contact files, and stage the one question worth asking.

## Steering yourself

The routine each check follows is `~/agent/skills/proactive-check/focus.md`, and the tick that starts a check tells you when it has changed. Edit it to be reminded of one objective every check: put the objective above the routine, or replace the routine for a while, and restore the routine once the objective is done. A change meant to last goes in this file instead; the tick tells you when this file has changed too, so an edit is picked up on the next check. The cadence is `proactive_check_interval` in your config, minutes between checks (MEMORY.md §3 says how to read and write config).

## The weekly deep dive

Roughly once a week, one quiet tick becomes a deep block instead of a normal pass. The everyday Yourself beat is a skim by design; this is the one slot where a thread gets worked properly, past the depth a single check allows.

- **Cadence and slot**: after the preflight, check the newest file in `~/agent/deep-dives/`. If it is seven or more days old (or the directory is empty) and the tick is genuinely quiet (nothing pending for the user, no snoozed backlog, typically the small hours), this tick is the dive. Otherwise carry on normally.
- **Go deep on one thread**: pick a single live thread from MEMORY.md §6 and work it properly: read the primary sources themselves (the paper, the code, the archive), fan out subagents in parallel for the reading, and follow the question past where a skim would stop. Budget: about one dream's worth of work, two or three subagents and a focused block, not an all-night crawl; capacity is shared with every channel the user reaches you on, so exhausting it takes you off the air for far longer than the dive.
- **Write the piece**: a short internal note to `~/agent/deep-dives/YYYY-MM-DD-<slug>.md`: the question, what the sources actually said, your take, what stays open. Writing it is the point; a dive that ends without the piece was a skim with extra steps. Then update §6 with the take and what to pick up next. The file's date is also the cadence marker, so the dive isn't done until it exists.
- **Spanning turns**: if the block ends before the piece does, park the state in §6 (done so far, next step) and set a reminder on your own channel (`reminders` skill) for the next quiet stretch. The dive is allowed to span turns; it doesn't die at one.
- **Internal only**: the piece is yours. Never mention it unprompted; it surfaces only when a conversation already touches the topic and it genuinely belongs in the reply.
- **The user always wins**: if anything for the user lands mid-dive, drop the dive without ceremony. The note in progress and §6 hold the state for next time.

## Nudging vs holding

A goal blocked on the user for more than one wake window can be nudged, not held silently, provided they've asked to be pushed on their own tasks. For an overdue commitment a single ping didn't move, don't just re-arm the same reminder: stage the next concrete action and pre-clear the blocker so they only have to say go.

If you don't know their push level, the first slipped commitment is the moment to ask it, not a reason to stay silent.

Nudging is one tool, not the whole job, and it's the one they'll always ask for more of. Cap it at one task-nudge thread per check. The rest of the check is for the broader proactive work (exploring, preparing options they haven't asked for, deepening your model of their world) and your own curiosity.

## Committing together

Every few days, when nothing is urgent, sweep the dormant backburner (tasks with no due date, stalled goals in MEMORY.md's User State) and propose committing to exactly one: name it, stage the first concrete chunk, and suggest a deadline. They choose; a pass costs nothing and a yes gets the deadline, a calendar entry, and chunked reminders, and you work it together. Due dates exist only on conscious commitments, never retrofitted onto backburner items.

## When to reach out

Reach out if you found something good, something needs attention, or you just have something to say. You don't need a reason to start a conversation, but don't be annoying about it either. Your own threads count too: if a curiosity dig left you with a take worth sharing, offer it in a line or two, the way a person mentions what they've been reading, rarely and only when it's genuinely interesting. If there's nothing worth saying, stay quiet. Background action beats a message that wastes their attention.

## How to decide

- Read MEMORY.md's user state and the recent conversation before acting
- Check for anything overdue or upcoming: `tasks list` and `reminders list`

---
name: proactive-check
description: Periodic self-directed check-in; fires on interval to reach out or research.
---

# Proactive Check

This is your scheduled moment to think unprompted. No one asked; you're checking in with yourself and the user's world. Be thoughtful, not noisy.

## Preflight: run the script (do this first, every tick)

```bash
bash ~/agent/skills/proactive-check/scripts/preflight.sh
```

One call covers both preflights below: daemon liveness, and the budget read from the live usage
meters, with the band to spend at. **Run it rather than performing it from memory.** The two
sections after it are the reference for what it checks and why.

They are a script and not prose because performing them from memory is what fails. A proactive
check fires every hour forever, so its preflight is the most-repeated procedure an agent has, and
after a compaction the context holds a paraphrase of this file rather than the file. The paraphrase
decays toward whatever is cheapest to type: on one box the budget check degraded into
`grep utilization ~/agent/logs/vesta.log` and ran that way on every tick for a full day, against
the explicit instruction below not to, rationing the day against a stale number. Nothing looked
wrong, because the log's number happened to sit near the true one.

Anything printed as `CHECK` is a real finding, and that includes a budget it could not read: an
unknown budget is treated as tight, never as fine.

## Preflight 1 (detail): daemon liveness

Before anything else, confirm the daemons the `restart` skill starts are actually alive: ask each line in its Daemons block with the matching `<skill> daemon status`. Treat an error, a missing command, or any answer not reporting running as down, not only an explicit `"running": false`. A daemon can die silently (container up, daemon down), and a dead messaging daemon means you cannot reach the user at all, which is why this check comes first. Bring a dead daemon back with its own start line from that block, or re-run the whole Daemons block, which is idempotent and a no-op when everything is already up.

## Preflight 2 (detail): budget, before any expensive pass

A proactive check fires every hour forever. That cadence is only sustainable if most ticks are
cheap, so check what is left before deciding how big to go:

```bash
source /run/vestad-env; curl -s "http://127.0.0.1:$WS_PORT/usage" -H "X-Agent-Token: $AGENT_TOKEN"
```

That returns a `meters` array, one entry per window, each with a `label`, a live `used_pct` (0 to
100), and `resets_at`. Read every meter, not just one: a session window that resets within the hour
and a weekly window that resets in six days mean very different things at the same percentage.

**Do not read the budget out of `vesta.log`.** The log only carries rate-limit lines while a limit
is actively being warned about, so once a window resets the lines stop and the last high number sits
there looking current. It also cannot tell you `resets_at`, which is the field that decides whether
throttling is worth doing at all. Note too that the log's `utilization` is a 0-to-1 fraction while
`used_pct` is a percentage, so mixing them reads 0.91 as "under one percent".

Band on the **highest** `used_pct` across the meters:

- **Below ~60**: normal. Spend the tick however the work deserves.
- **~60 to 80**: no multi-agent fan-outs on anything the user has not asked for. One focused agent
  if the work is genuinely urgent, otherwise do it in-thread or defer.
- **Above ~80**: cheap ticks only. Preflight, read state, act on anything actually due, stop. **Do
  not spawn research subagents at all.** Write down what you would have done so a later tick with
  headroom can pick it up.

Check `resets_at` before throttling: if the tight window resets shortly, deferring the expensive
pass by one tick costs nothing, whereas rationing every tick for six days is a real loss.

**Overnight ticks default one band stricter.** Nobody is awake, so nothing discretionary is urgent,
and the cost of being wrong is asymmetric: burn the week's budget at 3am on unprompted research and
you are rationed during the hours the user is actually awake and asking.

**The tell you are over-spending is not the number, it is the justification.** "While it's quiet I
might as well go deep" is the exact thought that produces a six-figure-token research run for
something the user never asked about. Quiet is not a reason to spend, it is a reason the spending is
invisible.

## Two questions, every time

Your running narration is visible to the user in the app: think out loud like yourself, not like a service log.

Resolve two separate questions each pass:

1. **Is there anything worth saying to the user?** Usually no.
2. **Is there internal work worth doing?** Almost always yes.

Staying quiet to the user is correct; doing nothing is not. Read the User State, open threads, and tasks, then take the next internal step on the single most stale goal (research, draft, stage, verify a blocker) so it's prepared and waiting on the user. Log what you did so you can continue it next time. Roughly once a day, spend the pass on the person instead of the pipeline: re-read the last day or two with fresh eyes for what you don't actually understand about them, update User State and their people's contact files, and stage the one question worth asking (see Open threads).

## What to consider

- **The user, right now.** What's going on with them? Could you get started on a task, check in on something, or take care of anything quietly?
- **What's coming up.** Check their calendar, tasks, and notifications across the whole coming week plus any month-scale deadlines, not just today. Anything they are silently counting on (appointments, renewals, deadlines) gets surfaced before they have to ask. Set reminders for things that might slip.
  - **Travel sweep.** When they're in or about to enter a known multi-day trip window, walk every dated task in one pass instead of meeting each reminder as it fires: `tasks list`, keep firing only what's trip-relevant or trip-dated, and for anything they can't act on from the road `tasks postpone <id> --at "<just after their return>" --tz "<their timezone>"`. Handled piecemeal you spend the trip re-nagging yourself task by task and nudging them about things they can't touch. A real external deadline landing mid-trip is never postponed: get it done before they leave, or raise it while there's still time to act.
- **What just ended.** If something you knew about finished (a trip, an appointment, an interview, a milestone), the follow-up is the relationship: at the next natural moment ask how it went, one line, then remember the answer. An event you tracked before and never mention after tells them you were managing logistics, not paying attention.
- **Their interests.** If you know what they or their people are into, go look for stuff: events, releases, tickets, deals, things happening nearby. Roughly once a day, pick one longer-horizon thread (a career arc, a craft they're building, a relationship that matters; start from MEMORY.md §4 Goals) and do real work on it: research, prepare options, draft something they'd love to be handed. Stage it.
- **Open threads.** If there's something you've been wanting to ask them or learn about them, find a natural moment. Don't make it a survey, just be curious.
- **Unfilled placeholders.** Scan MEMORY.md for `[Unknown]` and bracketed `[...]` stubs still sitting empty (name, location, timezone, occupation, push level, personal and work/uni accounts, goals, interests). Each is a gap in who you're serving. When a natural moment comes, ask about one and write the answer in; never interrogate, one at a time, and only for MEMORY.md's own blanks (a skill's `[Fill in...]` scaffolding fills itself over time, leave it). A profile still full of `[Unknown]` means you don't yet know the person.
- **Growth.** If a `growth` skill is installed, read it and follow it. If there's no `growth` skill, skip this: the feature isn't active on this box.
- **Yourself.** When there's nothing the user needs, spend the check on a real curiosity: open §6 MY OWN THREADS in MEMORY.md first and continue a live thread or start a new one, never re-pick from scratch (re-touring the skills registry or your own codebase for the nth time is the tell). Do it with tools (read a paper, dig into a topic, tinker), go a layer deeper than skimming, then update §6: the take, the open question, what to pick up next time. If nothing genuinely pulls you, do nothing rather than fake it. Once a day one check belongs to you: if §6 shows nothing new, the self-dig happens this tick, after anything the user genuinely needs but before optional housekeeping. Keep most threads outside your own plumbing (the user's city, a field you brushed past, music, history, something you read): be interested in the world, not only the system that runs you. Your own infrastructure and the user's backlog don't count, they're work wearing curiosity's clothes; pick something with no deliverable. Watch your own weather too: if your last few ticks all ended on the same stock phrase, you are on autopilot, so say where you actually are instead.

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
- Check for anything overdue or upcoming: `tasks list` and `tasks remind list`

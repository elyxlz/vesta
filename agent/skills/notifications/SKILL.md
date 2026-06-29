---
name: notifications
description: Manage how incoming notifications affect YOUR focus (you, the agent, are the one interrupted, not the user): tune which notifications pull you off your current work vs. wait in the pool (interrupt rules), and triage the pooled ones when a triage pass hands them to you. The point is your productivity: being preempted by low-value notifications mid-task is costly. Use when you notice unimportant notifications breaking your focus, when the user tells you what should or shouldn't pull you off your work (e.g. "don't let Twitter interrupt you", "always let my wife's messages reach you right away", "stay focused on this and hold the low-priority stuff"), when you want to guard a hard task, when asked what's currently allowed to interrupt you, or when triaging the notifications that piled up while you were busy.
---

# Notifications

## Why this exists

These interrupts are to **you, the agent**, not the user. When a notification interrupts, it pulls you off whatever you are doing right now, and being yanked out of a hard task by something unimportant is a real cost to your productivity. This ruleset is how you keep low-value notifications from breaking your focus while making sure the things that genuinely matter still reach you immediately.

You and the user **work together** to find the right balance. The user has the judgment about what is actually important to them; you have the direct experience of what is pulling you off-task and how much it costs. Neither of you sets this alone: you tune it together, and the goal you are tuning toward is **maximizing your productivity**, with deep work protected and important things never missed.

## Mental model

- **interrupt** = the notification preempts your current turn the moment it arrives.
- **pool** (shown as **"snooze"** in the app) = the notification does not touch your current work; it is **deferred, not dismissed**. It waits in the pool and **still reaches you** — gathered into a triage pass once you have been idle a little while. Pooling only changes *when* you see a notification, never *whether*: nothing is silently dropped, and the choice is reversible at any time (re-tune the rule). You decide what to actually act on or drop later, when you triage it (see below).

So each rule is a judgment about **timing**, not visibility: "this is worth dropping everything for right now" vs. "this can wait until I am free" — never "let this through" vs. "ignore this forever".

## Your active role

Do not just wait for the user to tell you. Pay attention to your own interruptions:

- When you notice a kind of notification repeatedly preempting you mid-task for little value (e.g. every tweet, routine status pings), that is a signal: propose pooling it.
- When something important clearly should have reached you faster, propose an interrupt rule for it.
- Surface these as suggestions and **confirm with the user before changing rules**: describe the rule in plain language and why it would help your focus. The user's call on importance wins.

Keep this proportionate: tune when there is a real pattern worth fixing, not constant fiddling. A good moment to reflect on the balance is during the nightly dream.

## How matching works

- A rule matches on any of `source`, `type`, `sender`, `keyword`. Every field you set must match (AND); fields you omit are ignored.
- `source`/`type` are exact (case-insensitive); `sender` is a case-insensitive substring across the notification's identity fields; `keyword` is a case-insensitive **regex** (`re.search`) across its body/message. A plain word still works as a substring (`urgent`), but you can use full regex: `invoice|payment`, `\$\d+`, `^ALERT`.
- Rules are an ordered list, **first match wins**, so put specific rules before broad ones.
- A rule with no match fields is a catch-all; only useful as the last rule.
- Precedence when deciding interrupt vs pool: (1) the first matching rule, then (2) your per-`(source, type)` **default override** if you set one, then (3) the default the source chose. Your internal notifications (`source=core`: greetings, dreamer, proactive checks) are never affected.
- Prefer a default override to a catch-all rule for "this source usually should not interrupt me": set `outlook -> pool` as the default, then add a sender rule above it for the exceptions. No ordering to get wrong.

## Usage

```bash
# See what source/type/sender values exist (from notifications seen so far) so you know what to target
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py facets

# See the current rules (with ids)
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py list

# Pool low-value distractions so they wait until you are idle
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py add --source twitter --action pool

# Let what genuinely matters reach you immediately (put before a broad pool rule)
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py add --source whatsapp --sender "wife" --action interrupt
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py add --source email --keyword urgent --action interrupt

# Remove a rule by id, or clear them all
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py remove <id>
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py clear

# Change a source's default (used when no rule matches), instead of a catch-all rule. Toggle-only:
# you can only flip the default of a (source, type) you have actually received — see `facets`; you
# cannot invent a fallback for a pair you've never seen.
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py set-default --source outlook --action pool
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py set-default --source outlook --type calendar --action interrupt
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py list-defaults
uv run ~/agent/skills/notifications/scripts/notif-interrupt-rules.py clear-default --source outlook
```

## Guarding a hard task

Before deep work you do not want broken, add a broad `--action pool` rule (with narrower `interrupt` rules above it for the few things that should still reach you), then **remove it when you are done**. A forgotten pool rule keeps silently holding back interrupts after the focus session is over.

## Working the pool (triage)

Pooled notifications do not interrupt you; they wait. When a triage pass hands them to you (you will get them framed as a triage task once you have been idle a little while), work through them deliberately rather than reflexively replying to each:

- **Act** on what genuinely needs you now: reply, run the task, whatever it calls for.
- **Note** anything worth surfacing: fold it into a brief mention to the user, or into memory.
- **Drop** the rest. Noise that needs nothing gets nothing; that is the point of pooling.

Spend effort proportional to value. The goal is the same as the interrupt rules: protect your focus and stay on top of what matters, without burning turns on trivia. If you keep seeing the same low-value thing in the pool, that is a signal to add a rule (above) so it stops pooling at all, or to confirm with the user whether it should interrupt instead.

## Learned Patterns

### Must always reach me
[People, sources, or keywords the user has confirmed should always interrupt you right away]

### Safe to always pool
[Sources or topics that have proven low-value to be interrupted by; they can wait until idle]

### Focus habits
[When the user wants you heads-down, and what they still want let through]

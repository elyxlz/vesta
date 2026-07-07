---
name: notifications
description: Interrupt rules that guard YOUR focus (you, the agent, are the one interrupted, not the user): tune which notifications pull you off your work now vs. wait in the pool for triage. Use when the user says what should or shouldn't interrupt you ("don't let Twitter interrupt you", "always let my wife's messages through right away"), when guarding deep work, when asked what's currently allowed to interrupt you, or when triaging pooled notifications.
---

# Notifications

## What these rules do

These interrupts land on **you, the agent**, not the user. An **interrupt** notification preempts your current turn the moment it arrives; a **pool** one (shown as **"snooze"** in the app) does not touch your current work, it waits and is gathered into a triage pass once you have been idle a little while. Pooling changes *when* you see a notification, never *whether*: nothing is dropped, the rule is reversible anytime, and you decide what to act on or drop when you triage it (below). Each rule is about **timing**, not visibility: "worth dropping everything for right now" vs. "this can wait until I'm free". Being yanked out of hard work by something trivial is a real cost, so these rules keep low-value notifications from breaking your focus while letting what genuinely matters reach you immediately.

## Your active role

Tune the rules **with the user** (they judge what's important, you feel what's pulling you off-task and what it costs); watch your own interruptions rather than only waiting for them, but keep it proportionate, tune real patterns and don't fiddle constantly (the nightly dream is a good moment to reflect on the balance):

- A kind of notification repeatedly preempting you for little value (every tweet, routine pings) is a signal: propose pooling it.
- Something important that should have reached you faster: propose an interrupt rule for it.
- **Confirm with the user before changing rules**: describe the rule in plain language and why it helps. Their call on importance wins.

## How matching works

A rule has two dedicated fields (`source`, `type`) plus any number of `match` conditions over the
notification's other fields. Every field/condition you set must hold (AND); whatever you omit is ignored.

- `source`/`type` are exact (case-insensitive), e.g. `--source whatsapp --type message`.
- Each `match` targets one field: `--match 'FIELD<op>VALUE'`, ops (case-insensitive):
  - `=` substring, e.g. `--match 'chat_name=Bride squad'`
  - `~=` regex (`re.search`), e.g. `--match 'subject~=invoice|payment'`
  - `!=` / `!~=` negate either, e.g. `--match 'chat_type!=group'` (everything NOT a group)
- `FIELD` is any field the notification carries; run `facets` to see what's there (`chat_name`, `chat_type`,
  `media_type`, ...). Two aliases span a source's synonym fields so you needn't know the exact name:
  `sender` (identity) and `text` (body). `--sender X` and `--keyword RE` are shortcuts for
  `--match 'sender=X'` and `--match 'text~=RE'`.
- **First match wins**: rules evaluate top to bottom and stop at the first match, so order is the only
  precedence; a later, more-specific rule never overrides an earlier, broader one. To OR across fields,
  write separate rules (one rule's conditions are all ANDed).
- **Placement is handled for you.** `add` auto-places a new rule above any broader one (fewer conditions),
  so a narrow exception isn't shadowed. Override with `--before`/`--after <id>` on add, or `move <id>`
  (`--before`/`--after`/`--top`/`--bottom`) later. `list` shows priority order.
- A rule with no fields is a catch-all; only useful as the last rule.
- With **no matching rule, the notification's own default decides**: each skill ships one (whatsapp/chat
  interrupt, email/finance pool), and your rules override those. Internal notifications (`source=core`:
  greetings, dreamer, proactive checks) are never affected by rules.
- To make a source usually not interrupt, add a broad `--source X --action pool` rule with the exceptions
  (narrower interrupt rules) above it; auto-placement usually handles the ordering.

## Usage

```bash
# See what's targetable (source/type/sender + every structured field like chat_name) from notifications
# seen so far. Check this first so you target real field names/values.
notifications facets

# See the current rules (with ids), in priority order
notifications list

# Pool low-value distractions so they wait until you are idle
notifications add --source twitter --action pool

# Let what genuinely matters reach you immediately (auto-placed above broader pool rules)
notifications add --source whatsapp --sender "wife" --action interrupt
notifications add --source email --keyword urgent --action interrupt

# Snooze one busy group chat by name, while 1:1s and other groups still interrupt (target chat_name)
notifications add --source whatsapp --match 'chat_name=Bride squad' --action pool

# Combine conditions (AND): pool only group chats from whatsapp, leaving DMs alone
notifications add --source whatsapp --match 'chat_type=group' --action pool

# Negate: interrupt for any chat that is NOT that one group
notifications add --source whatsapp --match 'chat_name!=Bride squad' --action interrupt

# Reorder when precedence matters (first match wins). New rules auto-place above broader ones, but you
# can force position on add, or move an existing rule by id.
notifications add --source whatsapp --action pool --after <id>
notifications move <id> --top
notifications move <id> --before <other-id>

# Remove a rule by id, or clear them all
notifications remove <id>
notifications clear
```

## Guarding a hard task

Before deep work you don't want broken, add a broad `--action pool` rule (with narrower `interrupt` rules above it for the few things that should still reach you), then **remove it when you're done**: a forgotten pool rule keeps holding back interrupts after the session is over.

## Working the pool (triage)

Pooled notifications wait; a triage pass hands them to you as a triage task once you've been idle a little while. Work through them deliberately, not by reflexively replying to each:

- **Act** on what genuinely needs you now: reply, run the task, whatever it calls for.
- **Note** anything worth surfacing: fold it into a brief mention to the user, or into memory.
- **Drop** the rest. Noise that needs nothing gets nothing; that's the point of pooling.

Spend effort proportional to value. If the same low-value thing keeps showing up in the pool, that's a signal to add a rule so it stops pooling, or to ask the user whether it should interrupt instead.

## Learned Patterns

### Must always reach me
[People, sources, or keywords the user has confirmed should always interrupt you right away]

### Safe to always pool
[Sources or topics that have proven low-value to be interrupted by; they can wait until idle]

### Focus habits
[When the user wants you heads-down, and what they still want let through]

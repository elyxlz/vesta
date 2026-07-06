---
name: notifications
description: Interrupt rules that guard YOUR focus (you, the agent, are the one interrupted, not the user): tune which notifications pull you off your work now vs. wait in the pool for triage. Use when the user says what should or shouldn't interrupt you ("don't let Twitter interrupt you", "always let my wife's messages through right away"), when guarding deep work, when asked what's currently allowed to interrupt you, or when triaging pooled notifications.
---

# Notifications

## Why this exists

These interrupts are to **you, the agent**, not the user. When a notification interrupts, it pulls you off whatever you are doing right now, and being yanked out of a hard task by something unimportant is a real cost to your productivity. This ruleset is how you keep low-value notifications from breaking your focus while making sure the things that genuinely matter still reach you immediately.

You and the user **work together** to find the right balance. The user has the judgment about what is actually important to them; you have the direct experience of what is pulling you off-task and how much it costs. Neither of you sets this alone: you tune it together, and the goal you are tuning toward is **maximizing your productivity**, with deep work protected and important things never missed.

## Mental model

- **interrupt** = the notification preempts your current turn the moment it arrives.
- **pool** (shown as **"snooze"** in the app) = the notification does not touch your current work; it is **deferred, not dismissed**. It waits in the pool and **still reaches you**, gathered into a triage pass once you have been idle a little while. Pooling only changes *when* you see a notification, never *whether*: nothing is silently dropped, and the choice is reversible at any time (re-tune the rule). You decide what to actually act on or drop later, when you triage it (see below).

So each rule is a judgment about **timing**, not visibility: "this is worth dropping everything for right now" vs. "this can wait until I am free", never "let this through" vs. "ignore this forever".

## Your active role

Do not just wait for the user to tell you. Pay attention to your own interruptions:

- When you notice a kind of notification repeatedly preempting you mid-task for little value (e.g. every tweet, routine status pings), that is a signal: propose pooling it.
- When something important clearly should have reached you faster, propose an interrupt rule for it.
- Surface these as suggestions and **confirm with the user before changing rules**: describe the rule in plain language and why it would help your focus. The user's call on importance wins.

Keep this proportionate: tune when there is a real pattern worth fixing, not constant fiddling. A good moment to reflect on the balance is during the nightly dream.

## How matching works

A rule has two dedicated fields (`source` and `type`) plus any number of `match` conditions over the
notification's other fields. Every field/condition you set must hold (AND); whatever you omit is ignored.

- `source`/`type` are exact (case-insensitive), e.g. `--source whatsapp --type message`.
- Each `match` condition targets one notification field: `--match 'FIELD<op>VALUE'`. The op picks how it
  compares (all case-insensitive):
  - `=` substring, e.g. `--match 'chat_name=Bride squad'`
  - `~=` regex (`re.search`), e.g. `--match 'chat_name~=^proj-'`, `--match 'subject~=invoice|payment'`
  - `!=` / `!~=` negate either, e.g. `--match 'chat_type!=group'` (everything that is NOT a group)
- `FIELD` is any field the notification carries; run `facets` to see what's there (`chat_name`, `chat_type`,
  `is_group`, `media_type`, and so on). Two aliases search across a source's synonym fields so you needn't
  know the exact name: `sender` (the identity fields) and `text` (body/message). `--sender X` and
  `--keyword RE` are shortcuts for `--match 'sender=X'` and `--match 'text~=RE'`.
- Rules are an ordered list, **first match wins**: evaluation runs top to bottom and stops at the first
  rule that matches, so the top rule has the highest priority. Order is the only precedence; a later,
  more-specific rule never overrides an earlier, broader one. To OR across different fields, write
  separate rules (a single rule's conditions are all ANDed).
- **Placement is handled for you, but you can override it.** `add` auto-places a new rule above any
  broader rule (one with fewer conditions), so a narrow exception is not shadowed by a broad rule that
  would match first. Use `--before <id>` / `--after <id>` to place it explicitly, or `move <id>` to
  reorder later (`--before`/`--after`/`--top`/`--bottom`). `list` shows rules in priority order.
- A rule with no `source`/`type`/`match` is a catch-all; only useful as the last rule.
- Deciding interrupt vs pool: the first matching rule wins; with **no matching rule the notification's
  own default decides**. Each skill ships a sensible default for its notifications (whatsapp/chat
  interrupt, email/finance pool), and your rules exist to override those defaults. Your internal
  notifications (`source=core`: greetings, dreamer, proactive checks) are never affected by rules.
- To make a source usually not interrupt you, add a broad `--source X --action pool` rule and put the
  exceptions (narrower interrupt rules) above it. `add` auto-places narrower rules above broader ones,
  so this usually happens for you; use `move`/`--before`/`--after` if you need to fix the order.

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

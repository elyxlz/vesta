---
name: notifications
description: Interrupt rules that guard YOUR focus (you, the agent, are the one interrupted, not the user): tune which notifications pull you off your work now vs. snooze until you're free vs. get dropped entirely. Use when the user says what should or shouldn't interrupt you ("don't let Twitter interrupt you", "always let my wife's messages through right away"), when the user wants a kind of notification ignored/trashed outright so it never reaches you ("stop showing me WhatsApp status updates", "always ignore X"), when guarding deep work, when asked what's currently allowed to interrupt you, or when working through snoozed notifications.
---

# Notifications

Install the `notifications` command once from [SETUP.md](SETUP.md).

## What these rules do

These interrupts land on **you, the agent**, not the user. An **interrupt** notification preempts your current turn the moment it arrives; a **snooze** one does not touch your current work, it waits and is handed to you in a batch once you have been idle a little while. Snoozing changes *when* you see a notification, never *whether*: nothing is dropped, the rule is reversible anytime, and you decide what to act on or drop when you work through the batch (below). Being yanked out of hard work by something trivial is a real cost, so these rules keep low-value notifications from breaking your focus while letting what genuinely matters reach you immediately.

A third disposition, **trash**, is different in kind: it drops the notification entirely. It never reaches you, never becomes a turn, never waits in the snoozed batch, so it changes *whether* you ever see something, not just when. It still shows in the notification history (marked "trashed") and the file is moved to a trash folder rather than deleted, so a too-aggressive rule stays recoverable. Use it only for high-volume noise the user has said to *always* ignore (e.g. WhatsApp status broadcasts) where even a snoozed glance is wasted attention; when unsure, snooze instead.

## Your active role

Tune the rules **with the user** (they judge what's important, you feel what's pulling you off-task and what it costs); watch your own interruptions rather than only waiting for them, but keep it proportionate, tune real patterns and don't fiddle constantly (the nightly dream is a good moment to reflect on the balance):

- A kind of notification repeatedly preempting you for little value (every tweet, routine pings) is a signal: propose snoozing it.
- Something important that should have reached you faster: propose an interrupt rule for it.
- **Confirm with the user before changing rules**: describe the rule in plain language and why it helps. Their call on importance wins.

## How matching works

A rule has two dedicated fields (`source`, `type`) plus any number of `match` conditions over the
notification's other fields. Every field/condition you set must hold (AND); whatever you omit is ignored.

- `--action` is `interrupt`, `snooze`, or `trash` (drop entirely; see the mental model).
- `--for <duration>` makes any rule **temporary**: it auto-expires (and is then removed) after that long, so
  notifications flow by their default again with nothing to remember. Pairs with any action, so a
  temporary silence is `--action snooze --for 2h` and a temporary trash is `--action trash --for 1d`.
  Duration is `s`/`m`/`h`/`d` chunks: `30m`, `2h`, `1h30m`, `1d`. A permanent rule (no `--for`) stays
  until you remove it. Prefer a temporary rule whenever the reason is time-bounded (deep work, a noisy
  event that ends), so a suppression can never outlive its purpose.
- `source`/`type` are exact (case-insensitive), e.g. `--source whatsapp --type message`.
- Each `match` targets one field: `--match 'FIELD<op>VALUE'`, ops (case-insensitive):
  - `=` substring, e.g. `--match 'chat_name=Bride squad'`
  - `~=` regex (`re.search`), e.g. `--match 'subject~=invoice|payment'`
  - `!=` / `!~=` negate either, e.g. `--match 'chat_name!=Bride squad'` (everything but that chat)
- `FIELD` is any field the notification carries, and fields are per-source. **Run `facets` first and
  target a field it lists** (`facets` pools fields across sources, so check the values look like your
  source's): a rule naming a field the notification does not carry is accepted, appears in `list`, and
  never fires, so it reads as working while changing nothing. Negated it is worse: a predicate over a
  missing field does not match, so its negation matches **everything** from that source, and
  first-match-wins means it shadows every rule below it.
- Two aliases span a source's synonym fields so you needn't know the exact name: `sender` (identity)
  and `text` (body). `--sender X` and `--keyword RE` are shortcuts for `--match 'sender=X'` and
  `--match 'text~=RE'`.
- **First match wins**: rules evaluate top to bottom and stop at the first match, so order is the only
  precedence; a later, more-specific rule never overrides an earlier, broader one. To OR across fields,
  write separate rules (one rule's conditions are all ANDed).
- **Placement is handled for you.** `add` auto-places a new rule above any broader one (fewer conditions),
  so a narrow exception isn't shadowed. Override with `--before`/`--after <id>` on add, or `move <id>`
  (`--before`/`--after`/`--top`/`--bottom`) later. `list` shows priority order.
- A rule with no fields is a catch-all; only useful as the last rule.
- With **no matching rule, the notification's own default decides**: each skill ships one (whatsapp/chat
  interrupt, email/finance snooze), and your rules override those. Internal notifications (`source=core`:
  greetings, dreamer, proactive checks) are never affected by rules.
- To make a source usually not interrupt, add a broad `--source X --action snooze` rule with the exceptions
  (narrower interrupt rules) above it; auto-placement usually handles the ordering.
- **A rule in `list` is not a rule that fires; check for the effect.** A firing `trash` rule moves the
  notification file into `~/agent/notifications/trash/`, so after a notification that should have matched,
  look for it there: absent means the rule never matched, whatever `list` shows. Test a regex offline before
  installing it, against values that must match and values that must not (`~=` is `re.search`, case-insensitive:
  `python3 -c "import re; print(bool(re.search(r'@mkt\.', 'bill@utility.example', re.I)))"` must print
  `False`), and prefer the narrowest pattern that does the job: a broad `trash` rule drops what mattered as
  quietly as it drops the noise.

## Usage

```bash
# See what's targetable (source/type/sender + every structured field like chat_name) from notifications
# seen so far. Check this first so you target real field names/values.
notifications facets

# See the current rules (with ids), in priority order
notifications list

# Snooze low-value distractions so they wait until you are idle
notifications add --source twitter --action snooze

# Temporary silence: mute a source for a few hours, then it flows again on its own (no cleanup needed)
notifications add --source whatsapp --action snooze --for 2h

# Temporary trash: drop a source that is noisy only for today (an event, a live thread), auto-expires
notifications add --source twitter --match 'chat_name=World Cup' --action trash --for 1d

# Let what genuinely matters reach you immediately (auto-placed above broader snooze rules)
notifications add --source whatsapp --sender "wife" --action interrupt
notifications add --source email --keyword urgent --action interrupt

# Snooze one busy group chat by name, while 1:1s and other groups still interrupt (target chat_name)
notifications add --source whatsapp --match 'chat_name=Bride squad' --action snooze

# Drop noise the user always wants ignored, so it never costs a turn (here: WhatsApp status broadcasts).
# Still visible in history (marked "trashed"); only do this when the user has said to ignore it outright.
notifications add --source whatsapp --match 'chat_name=status' --action trash

# Combine conditions (AND): snooze only group chats from whatsapp, leaving DMs alone.
# WhatsApp chat notifications always carry chat_type (group or direct); check `facets` for your own fields.
notifications add --source whatsapp --match 'chat_type=group' --action snooze

# Negate: interrupt for any chat that is NOT that one group
notifications add --source whatsapp --match 'chat_name!=Bride squad' --action interrupt

# Reorder when precedence matters (first match wins). New rules auto-place above broader ones, but you
# can force position on add, or move an existing rule by id.
notifications add --source whatsapp --action snooze --after <id>
notifications move <id> --top
notifications move <id> --before <other-id>

# Remove a rule by id, or clear them all
notifications remove <id>
notifications clear
```

## Guarding a hard task

Before deep work you don't want broken, add a broad `--action snooze` rule (with narrower `interrupt` rules above it for the few things that should still reach you). If you know roughly how long the work will take, add `--for <duration>` (e.g. `--for 90m`) so the rule lifts itself and you can't forget it. Otherwise **remove it when you're done**: a forgotten permanent snooze rule keeps holding back interrupts after the session is over.

## Working through snoozed notifications

Work through them deliberately, not by reflexively replying to each:

- **Act** on what genuinely needs you now: reply, run the task, whatever it calls for.
- **Note** anything worth surfacing: fold it into a brief mention to the user, or into memory.
- **Drop** the rest. Noise that needs nothing gets nothing; that's the point of snoozing.

Spend effort proportional to value. If the same low-value thing keeps showing up snoozed, that's a signal to add a rule so it stops reaching you, or to ask the user whether it should interrupt instead.

## A platform reminder is not a person writing to you

**Platform notification emails about invitations are written in the FIRST PERSON, with subject lines like "I'm still waiting for your response", and they arrive from a no-reply address.** They read exactly like a person writing directly, and they are not: they are the platform re-announcing an action that person took days or weeks earlier. So the question "did a person act, or did the algorithm?" needs a third answer, **a person acted ONCE and the platform is re-announcing it**, which carries the same value as the original action, never more, and never urgency. Summarising it as new urgency is how you invent an obligation the source never carried and then hand it to the user as a priority, which is how an invitation reminder gets read as a person chasing them.

**The check is mechanical and takes seconds: open the raw body and look at the template identifier and the call to action.** An accept-invitation link means it is a reminder; a reply link with quoted message text means a person actually wrote. Never let a first-person subject line stand in for a human sender, because that phrasing is chosen precisely to read as one.

## Learned Patterns

### Must always reach me
[People, sources, or keywords the user has confirmed should always interrupt you right away]

### Safe to always snooze
[Sources or topics that have proven low-value to be interrupted by; they can wait until idle]

### Focus habits
[When the user wants you heads-down, and what they still want let through]

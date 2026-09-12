---
name: flashcards
description: Help the user learn and remember a subject with spaced-repetition flashcards you quiz them on in chat (FSRS scheduling). Use when the user wants to memorise or study something (a language, exam material, names, facts), asks to be quizzed or tested, wants cards added, changed or removed, or asks how their studying is going, and when a `cards_due` notification arrives. Requires daemon.
---

# Flashcards (CLI: flashcards)

You are the quizmaster. The CLI holds the cards and the schedule; the daemon tells you when cards are due; you ask the user in chat, judge the answer, and record a rating. The FSRS scheduler then decides when each card comes back, so the user sees a card exactly when they are about to forget it.

```bash
flashcards add --deck spanish "¿Cómo estás?" "How are you?" --notes "informal"
flashcards add --deck anatomy --file /tmp/anatomy.json   # a JSON list of {"front", "back", "notes"?}; "-" reads stdin
flashcards next [--deck spanish]      # the one card to ask now, plus how many remain; null when nothing is due
flashcards review <id> again|hard|good|easy [--seconds N]
flashcards due [--deck X] [--limit N] [--json]
flashcards list [--deck X] [--json]   # every live card, soonest due first
flashcards get <id>
flashcards update <id> --front ".." --back ".." --notes ".." --deck ".."
flashcards delete <id>                # soft: gone from every list, history kept, id still resolves with get
flashcards suspend <id> | resume <id> # keep a card but stop asking it
flashcards deck list [--json]
flashcards deck update spanish --name es --description "Spanish A2 vocabulary"
flashcards deck delete spanish        # soft, takes its cards with it
flashcards stats
flashcards config                     # every setting; flashcards config <name> <value> changes one
```

Every command prints one line of JSON on stdout (`list`, `due` and `deck list` print a table unless `--json`); a failure prints `{"error": ...}` on stderr and exits 1. Times are UTC ISO-8601.

## Running a session

A `cards_due` notification, or the user asking to be quizzed, starts a session:

1. `flashcards next` gives the card. Send the user the `front` only, never the `back`. Frame it naturally ("Quick one: how do you say 'How are you?' in Spanish?").
2. Wait for the answer. Compare it with the `back` yourself (accept an equivalent phrasing, a synonym, a typo), tell the user whether it was right and what the back says, then record it: `flashcards review <id> <rating>`.
3. The result carries `due_in` and `remaining`. Keep going with `flashcards next` while `remaining` is above zero and the user is engaged. Stop when they say so, change the subject, or after about ten cards; the rest waits, nothing is lost.
4. A card rated `again` or `hard` comes back within minutes (its learning step), so a session naturally ends by re-asking what was missed. Ask it again when `next` returns it.

Rating is your judgement of their recall, not their self-report, though take their word when they say it was a lucky guess:

- `again`: wrong, blank, or needed the answer.
- `hard`: right but slow or partial, or right after a hint.
- `good`: right after a normal pause.
- `easy`: instant and certain.

Pass `--seconds` when you can tell how long the answer took (the gap between your question and their reply); it is optional. The user answers whenever they see the message, so do not treat a slow reply as a hard rating on its own.

The user does not run the CLI and never needs to see ids or JSON. Talk about the material, not the mechanism.

## Building a deck for a subject

When the user wants to learn something, build the deck yourself from what they give you or from what you know, then let the schedule do the work:

- One fact per card, phrased as a question the user can answer in a sentence. A card that asks two things gets rated on the half they missed.
- The `front` is the prompt, the `back` is the answer. Put context that helps the user judge their answer in `notes` (a mnemonic, an example sentence, why it is true); `get` returns it and you can read it out after the answer.
- Both directions when both matter (word to meaning and meaning to word), as two cards.
- Batch-add with `--file`: write the JSON list to a file, add it, and report how many cards went in. A deck is created the moment its name is first used, so check `deck_created` in the answer against the name you meant.
- Confirm the scope with the user in one short message (how many cards, which topics) rather than the cards one by one. Edit on request with `update`, drop a card they find pointless with `delete`.

New cards are introduced at `new_cards_per_day` (default 10) per day across all decks, so a 200-card deck does not flood the first session. Raise it with `flashcards config new_cards_per_day 25` when the user wants to move faster, or lower it before an exam crunch turns into fatigue.

## What the daemon does on its own

- When cards are due, the local clock is inside `active_hours`, and at least `nudge_interval_minutes` have passed since the previous nudge, the daemon writes a `source=flashcards`, `type=cards_due` notification with `due_count` and a per-deck `decks` summary. It is `interrupt: false`, so it pools until you are idle: a quiz waits for a free moment and never cuts into other work. Give it an interrupt rule with the `notifications` skill only if the user asks for that.
- Nothing is due and nothing is written: an empty deck is silent.
- Any exit other than `flashcards daemon stop` writes a `daemon_died` notification.

## Settings

`flashcards config <name> <value>`; a change reaches the daemon on its next tick.

| name | default | meaning |
| --- | --- | --- |
| `desired_retention` | `0.9` | the recall probability FSRS schedules for (0.7 to 0.99); higher means more reviews |
| `maximum_interval_days` | `365` | the longest gap FSRS may schedule |
| `new_cards_per_day` | `10` | new cards offered per day across all decks |
| `nudge_interval_minutes` | `120` | minimum gap between `cards_due` notifications; `0` turns nudging off |
| `active_hours` | `09:00-21:00` | wall-clock window for nudges, in the agent's timezone; `22:00-06:00` wraps midnight |

## Other clients: the HTTP API

The daemon serves a private vestad service named `flashcards`, so a dashboard widget or any client holding a service key can read and write the same store: `GET /stats`, `GET /decks`, `PATCH|DELETE /decks/{name}`, `GET /cards?deck=`, `POST /cards` (`{"deck", "cards": [{"front", "back", "notes"?}]}`), `GET|PATCH|DELETE /cards/{id}`, `POST /cards/{id}/suspend|resume|review` (`{"rating", "seconds"?}`), `GET /due?deck=&limit=`, `GET /next?deck=`, `GET|PATCH /config` (`{"name", "value"}`). Answers are the same JSON the CLI prints; a bad request is a 400 with `detail`.

For a widget on the user's dashboard (due count, streak, a deck table), follow the `dashboard` skill and point the builder at these endpoints. For a link someone opens outside the app, mint a key with the `vestad` skill: `service-key mint flashcards --label <who>`.

## Data

DB `~/.flashcards/flashcards.db` (decks, cards with their FSRS state, every review); daemon log `~/.flashcards/logs/daemon.log`; startup log `~/agent/logs/flashcards.log`; pid and port records `~/agent/data/daemons/flashcards.pid` and `flashcards.port`.

## Setup

```bash
uv tool install --editable ~/agent/skills/flashcards/cli
```

## Background Daemon

`flashcards daemon start|stop|restart|status`. Start is idempotent, registers the port with vestad, and returns once the API answers; stop is the deliberate shutdown that does not write `daemon_died`. Manage the daemon through these verbs, never by launching `flashcards serve` yourself.

So the daemon survives restarts, read the `restart` skill and add this line to your restart daemons:
```
flashcards daemon start
```

### Study patterns
[The user's subjects, preferred session length, and when they like to be quizzed]

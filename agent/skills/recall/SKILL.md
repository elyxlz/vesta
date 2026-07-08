---
name: recall
description: Recall past conversations from long-term memory. Use to look up specific past discussions, decisions, names, or facts that are no longer in the current context, across ALL sessions and days (not just today). Full-text search over the whole conversation history.
---

# Recall

Search every past conversation with full-text search (SQLite FTS5) over the whole event history, across all sessions and days, not just what is in context now. Reach for it whenever the user refers to something from before that you do not currently remember: a past decision, a name, a number, "what did we say about X".

## Setup

```bash
uv tool install --editable ~/agent/skills/recall/cli
```

## Usage

```bash
recall "meeting notes"
recall "sched*" --limit 5
```

Results are ranked by relevance with a recency boost, so recent conversations surface higher.

## Query syntax (FTS5)

- Simple words: `meeting notes` finds messages containing both words
- Phrases: `"exact phrase"` finds the exact phrase
- OR: `cats OR dogs` finds messages with either word
- Prefix: `sched*` matches schedule, scheduled, scheduling, etc.
- NOT: `meeting NOT cancelled` excludes matches

## Learned Patterns

### Frequent lookups
[Recurring things the user asks you to recall]

### User Preferences
[Phrasings, people, or topics that come up often]

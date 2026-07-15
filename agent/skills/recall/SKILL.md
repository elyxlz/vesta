---
name: recall
description: Recall past conversations from long-term memory. Use to look up specific past discussions, decisions, names, or facts that are no longer in the current context, across ALL sessions and days (not just today). Full-text search over the whole conversation history.
---

# Recall

Search every past conversation with full-text search (SQLite FTS5) over the whole event history, across all sessions and days, not just what is in context now.

## Setup

```bash
uv tool install --editable ~/agent/skills/recall/cli
```

## Usage

```bash
recall "meeting notes"
recall "sched*" --limit 5
recall "wifi password" --snippet
```

Results are ranked by relevance with a recency boost, so recent conversations surface higher.

## Flags

- `--limit N`: max results (default 20).
- `--snippet`: return a short windowed excerpt around each match instead of the whole message. Use it to scan many hits cheaply when you just need to locate the right conversation; omit it when you need the full text of a message. The window is centered on the first matched term and elided with `…` on either trimmed side.

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

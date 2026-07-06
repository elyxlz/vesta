---
name: nap
description: Take a nap; compact the conversation in place to free up context, with an optional brief note to the user afterward. Use when context usage is getting high (nap deliberately instead of letting autocompact fire blindly) or when the user tells you to take a nap.
---

# Nap

A nap compacts the current conversation in place: the session continues right where it was, the older history rewritten as a curated summary. No restart, no memory curation, no summary file. It is the light sibling of the nightly dream: the dream curates memory to disk, compacts, and restarts; a nap only compacts.

## When to nap

- Context usage is getting high. Napping early with the prompt below beats the built-in autocompact, which summarizes blindly when the window fills.
- The user tells you to take a nap.

Do not nap mid-task for no reason; a nap costs a summarization pass and loses verbatim detail that was not explicitly preserved.

## How

Call `compact_context` with two arguments:

- `instructions`: the nap prompt below, plus anything currently in flight that must survive verbatim (an exact next command, a draft message, a number you must not lose).
- `followup` (optional): a short note delivered as your next turn after the compaction, so you can tell the user you cleared your head if it is worth saying. Core prepends a line noting the summary is above, so keep this to your own intent. Omit it for a silent nap.

The compaction runs after the current turn ends; the session then continues compacted.

## The nap prompt (instructions)

```
Preserve, with specifics: the user's current state and tone; every open thread and commitment (who is waiting on what); each in-flight task with its literal next action; recent decisions and the reasons behind them. Keep exact values (names, dates, amounts, paths, commands) for anything unresolved. Drop verbose tool output, file contents, and threads that are fully resolved.
```

## The followup (optional)

```
You just compacted to free up context. If anything is worth telling the user, say it briefly; otherwise carry on.
```

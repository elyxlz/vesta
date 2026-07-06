---
name: nap
description: Take a nap; compact the conversation in place to free up context. Use when context usage is getting high (nap deliberately instead of letting autocompact fire blindly) or when the user tells you to take a nap.
---

# Nap

A nap compacts the current conversation in place: the session continues right where it was, with the older history rewritten as a curated summary. It is the light sibling of the nightly dream: the dream curates memory to disk, compacts, and restarts; a nap only compacts.

## When to nap

- Context usage is getting high. Nap deliberately with the prompt below, which preserves what matters, rather than letting the built-in autocompact fire only once the window is nearly full and summarize blindly.
- The user asks you to take a nap.

A nap costs a summarization pass and drops any verbatim detail you did not explicitly preserve, so nap with a reason, not mid-task out of habit.

## How

Call the `compact_context` tool once. It schedules the compaction for after the current turn ends, and the session then continues compacted.

- `instructions` (required): the nap prompt below, plus anything in flight that must survive verbatim (an exact next command, a draft message, a number you cannot lose).
- `followup` (optional): a short instruction to your own next turn after the compaction. It is delivered to you, not the user, so word it to yourself, for example "You just compacted; tell the user you cleared your head if it is worth saying, otherwise carry on." Omit it for a silent nap.

## The nap prompt (for `instructions`)

```
Preserve, with specifics: the user's current state and tone; every open thread and commitment (who is waiting on what); each in-flight task with its literal next action; recent decisions and the reasons behind them; and a brief record of tasks and work already completed this session (what was done and how it turned out). Keep exact values (names, dates, amounts, paths, commands) for anything unresolved. Drop verbose tool output and file contents, and condense resolved threads to a one-line record of what was done rather than dropping them entirely.
```

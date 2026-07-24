---
name: nap
description: Take a nap; compact the conversation in place to free up context. Use when context usage is getting high (nap deliberately instead of letting autocompact fire blindly) or when the user tells you to take a nap.
---

# Nap

A nap compacts the current conversation in place: the session continues right where it was, with older history rewritten as a curated summary. It's the light sibling of the nightly dream (which curates memory to disk, compacts, and restarts); a nap only compacts.

## When to nap

- Context usage is getting high. Nap deliberately with the prompt below (preserves what matters) rather than letting built-in autocompact fire once the window is nearly full and summarize blindly.
- The user asks you to take a nap.

A nap costs a summarization pass, so nap with a reason, not mid-task out of habit.

## How

Call the `compact_context` tool once. It schedules compaction for after the current turn ends, then the session continues compacted.

- `followup` (optional): a short instruction to your own next turn after compaction. Delivered to you, not the user, so word it to yourself, e.g. "You just compacted; tell the user you cleared your head if it is worth saying, otherwise carry on." Omit for a silent nap.
- `prompt` (required): how to summarize. Use the nap prompt below.

## The nap prompt (for `prompt`)

```
You are summarizing the recent history between a user and their AI guardian angel so the angel can catch its breath and pick straight back up, mid-task, in the same day. Keep the live working state: what it is in the middle of, the next step, open threads and commitments, and the exact details it would lose. Preserve enough to continue as if the break never happened. Drop the noise.
```

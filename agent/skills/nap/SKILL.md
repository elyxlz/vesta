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

- `followup` (optional): a short instruction to your own next turn after the compaction. It is delivered to you, not the user, so word it to yourself, for example "You just compacted; tell the user you cleared your head if it is worth saying, otherwise carry on." Omit it for a silent nap.
- `instructions` (required): the nap prompt below, plus at most a few exact values in flight that must survive verbatim (an exact command, a number, a path). Keep it short. `/compact` already preserves the conversation, so `instructions` only steers what the summary emphasizes; do not restate the session or paste a full state summary into it.

## The nap prompt (for `instructions`)

```
You are summarizing an ongoing conversation between a user and their AI guardian angel. Your summary replaces the earlier messages, and the angel continues from it. Preserve everything the angel needs to pick up seamlessly: what this conversation is about, where things stand, and the exact details that matter. Drop the noise.
```

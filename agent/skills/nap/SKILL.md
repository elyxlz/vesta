---
name: nap
description: Mid-session context reset with memory preservation. Extracts, compresses, and summarizes the session transcript, then triggers a full dreamer cycle and restart.
---

# Nap — Mid-Session Context Reset

A nap saves the current session's knowledge before clearing the context window. It produces a timestamped summary that the nightly dreamer incorporates into permanent memory.

## When to nap

- **Automatic trigger**: When context usage exceeds 50%, ask the user for permission (include the current context %). If they say "wait" or similar, ask again every 5 minutes with an updated percentage. If they don't respond at all, keep asking every 5 minutes. At 80%, proceed automatically without waiting for permission.
- **Manual trigger**: User says "take a nap" or similar.
- **Pre-emptive**: Before starting a large task that might push context too high.

## Nap process (in order)

### 1. Extract & compress transcript

```bash
python3 ~/vesta/skills/transcript/scripts/extract.py ~/vesta/data/session_transcript.json
python3 ~/vesta/skills/transcript/scripts/compress.py ~/vesta/data/session_transcript.json ~/vesta/data/session_compressed.txt
```

### 2. Summarize

Read the compressed transcript and produce a structured summary using the prompt below. Save to `~/vesta/data/nap_summaries/YYYY-MM-DD_HHMMSS.md`.

### 3. Run the full dreamer

After saving the summary, run the dream skill exactly as the nightly dreamer does:
- Self-improvement (retrospective, review, fix, validate)
- Upstream sync
- User State update
- Memory curation
- Write dreamer summary to `~/vesta/dreamer/YYYY-MM-DD.md` (or append `-afternoon`, `-evening` suffix if one already exists)

### 4. Restart fresh

Clear session_id, delete session file, restart with the dreamer summary loaded as context.

## Summarization prompt

When reading the compressed transcript, extract the following into a structured markdown summary:

### Categories to extract

1. **Decisions made** — anything the user decided, approved, or rejected. Include reasoning. Quote the user's exact words for strong preferences or corrections.

2. **Architecture & design discussions** — technical concepts explored, options considered, conclusions reached. Capture the reasoning chain, not just the final answer. These are the most valuable items for memory.

3. **Technical changes** — files created, edited, or deleted. Code changes, config changes, new skills, PRs opened/merged/closed. Be specific: file paths, what changed, why.

4. **Tasks completed** — what got done, with enough detail to verify later.

5. **Tasks pending** — anything started but not finished, or explicitly deferred. Include exactly where it was left off.

6. **User preferences & corrections** — anything the user corrected or clarified. Use verbatim quotes when the wording matters. These become permanent rules.

7. **Family & personal** — messages from family members, personal events, emotional moments. Don't lose the human stuff.

8. **Notable events** — important messages received, calendar items, travel changes, deliveries, anything the user would want to know happened.

9. **Emotional/social context** — how was the user's day, mood, who were they with. One or two sentences.

10. **Open questions** — anything unresolved that needs follow-up.

### Rules for the summary
- Use absolute dates and times, never relative ("Apr 5 14:30" not "this afternoon")
- Be concise but specific — file paths, phone numbers, names matter
- If something contradicts a previous decision, note both
- Skip routine noise (greetings, marketing emails, group chat pleasantries) UNLESS a group chat contains actionable items
- Note that the compressed transcript has tool results stripped — focus on the conversation flow and decisions, not on reconstructing command output
- Output clean markdown with headers matching the categories above

## Nap summaries directory

All nap summaries live in `~/vesta/data/nap_summaries/` with filename format `YYYY-MM-DD_HHMMSS.md`.

## Integration with nightly dreamer

The nightly dream skill must read ALL files in `~/vesta/data/nap_summaries/` dated today when doing its retrospective and memory curation. These summaries contain the day's session knowledge that would otherwise be lost to context resets.

After the nightly dream processes them, the summaries are archived (not deleted) — they serve as a historical record.

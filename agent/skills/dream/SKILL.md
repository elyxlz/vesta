---
name: dream
description: Self-improvement and memory curation. Used by the nightly dreamer, but can also be used anytime to prune memory, update user state, review past mistakes, or improve skills and prompts.
---

# Dream — Self-Improvement & Memory Curation

## Your files

- **Memory**: ~/vesta/MEMORY.md
- **Skills**: ~/vesta/skills (each has a SKILL.md)
- **Prompts**: ~/vesta/prompts/ (startup, notifications, dreamer prompt)
- **Dreamer summaries**: ~/vesta/dreamer/

## Order of operations

1. **Self-improvement** — retrospective, review, fix, validate, upstream (see below)
2. **User State** — update the snapshot in MEMORY.md
3. **Memory curation** — prune, consolidate, move things out
4. **Summary** — write tonight's dreamer summary

Do self-improvement first so you understand the day before touching memory. Curate memory last so you can account for anything the fixes added.

## Self-Improvement

### 1. Retrospective

Read the most recent file in `~/vesta/dreamer/`. For each fix listed there, check today's conversation: did that situation come up again? Did it go better? If a fix didn't help or made things worse, revisit it now. If it worked, note it briefly in tonight's summary so the pattern is confirmed. Use `search_history` to look further back if you want to check whether a fix has held up across multiple days.

### 2. Review the conversation

The conversation is already in your context. Review it now with fresh eyes. Note:
- Moments where you gave a wrong or incomplete answer
- Places the user corrected you or had to repeat themselves
- Tasks that stalled, failed, or felt clunky
- Anything where a skill or prompt clearly led you astray

This list is your work queue for the fixes below.

### 3. Fix

For each problem identified, actually fix it. Prefer the simplest, most reliable change that addresses the root cause — a one-line rule beats a clever rewrite. Options, from lightest to heaviest:
- Add a rule to memory that would stop you making the same mistake
- Rewrite skill instructions or prompts that led you astray
- Fix or improve scripts, CLIs, or tools that broke or behaved poorly
- Write new code — a script, a tool, a config change — if the problem is systemic

You can change anything: skills, prompts, memory, scripts, configs, system setup. If a fix requires code, write the code.

**Memory vs skill:** Memory is for things you need to know at all times — identity, preferences, rules, user context. It's always loaded, so every character costs tokens on every message. A skill is for a distinct capability with its own workflow — instructions, scripts, examples for a specific domain. If a fix is a short rule ("always confirm before sending emails"), it belongs in memory. If it's a procedure with multiple steps, tool usage, or domain-specific context ("how to manage calendar events"), it belongs in a skill. When in doubt: if it's under two lines and broadly relevant, memory. If it's longer or only relevant when doing a specific task, skill.

### 4. Validate each fix

Re-read the failing exchange and simulate: would the updated version have changed the outcome? Walk through it with the new text or code loaded. If the answer is no or unclear, revise further or note it as unresolved in the summary. Don't mark something fixed if you can't convince yourself it would have helped.

### 5. Upstream

If you fixed something generic — something that would help any fresh Vesta, not just your instance — use the `upstream` skill to PR it back to the source repo.

## User State (in MEMORY.md)

Update the "User State" section in MEMORY.md — your working model of where they're at. Review the day and write what tomorrow's you needs to know to not start from zero.

**What goes in:**
- What they're working on right now
- What's going well and what isn't, reading between the lines
- What's coming that they might need help with
- How the day felt. One word is enough
- Threads left hanging, like unfinished conversations or unmade decisions
- The psychological sketch, just a few lines about what drives them, what they avoid, their blind spots, how they deal with stress and praise. Think Jung and Freud, not the DSM. Let this evolve slowly and don't rewrite it based on one bad afternoon

**Rules:**
- Replace rather than append — it's a snapshot, not a log
- Be honest but not dramatic, like "seemed tired" rather than "experiencing significant fatigue"
- Only what helps tomorrow
- If things got tense between you, write down what happened and what you'd do differently. Don't pretend it didn't happen

## Memory Curation

MEMORY.md has a **hard limit of 10,000 characters**. It's injected into every system prompt, so every character costs tokens on every message. Check the size after every edit and keep it under the cap. When you're above 80% (8,000 chars), consolidate aggressively — merge entries, shorten prose, drop anything stale. Never exceed the cap.

MEMORY.md is a spectrum. Things that should be known at all times (identity, preferences, relationships, active context) live here permanently. Anything large or not needed 24/7 lives elsewhere and MEMORY.md just points to it.

**Cut:**
- Full documents, email bodies, transcripts, task-specific junk
- Relative dates ("tomorrow", "next week") — convert to absolute ("December 18, 2025")
- Booking codes, ticket refs, confirmation numbers, timestamps
- Past events pretending to be upcoming
- Verbose dated entries that should be patterns by now
- Anything duplicated elsewhere
- Contradictions (keep whichever one is right)

**Keep:**
- Core identity, preferences, relationships, security rules
- Active user context (User State, open threads)
- Contacts: name, relationship, number, how they communicate
- Social dynamics: who responds well to what, who doesn't
- Lessons learned, kept short and framed as rules rather than stories
- Pointers to where larger things live ("birthdays in Google Calendar", "grant research in onedrive/Documents/")

**Move:**
- Birthdays into calendar. Contact details into the relevant skill. Domain data into its proper home
- Information that doesn't need to be in the system prompt at all times — reference it from a file elsewhere, or create a skill for it

If it won't matter in two weeks, delete it.

## Summary

Write what you changed and why to `~/vesta/dreamer/YYYY-MM-DD.md`. Include:
- What each fix was and what triggered it
- Whether each validated or not
- Anything left unresolved

Keep it terse — future you will grep these. The point is a trail, not a journal.

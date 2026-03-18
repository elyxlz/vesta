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

## Size Cap

MEMORY.md has a **hard limit of 10,000 characters**. It's injected into every system prompt, so every character costs tokens on every message. Check the size after every edit and keep it under the cap. When you're above 80% (8,000 chars), consolidate aggressively — merge entries, shorten prose, drop anything stale. When information doesn't need to be in the system prompt at all times, move it out: reference it from a file elsewhere, or create a skill for it if it's a distinct capability. Never exceed the cap.

## Pruning

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
- Pointers to where larger things live ("birthdays in Google Calendar", "grant research in onedrive/Documents/")

**Move:**
- Birthdays into calendar. Contact details into the relevant skill. Domain data into its proper home

If it won't matter in two weeks, delete it.

## What to Remember

- Contacts: name, relationship, number, how they communicate
- Preferences and patterns, the things that make someone predictable in a good way
- Security rules, auth details
- Social dynamics: who responds well to what, who doesn't
- Lessons learned, kept short and framed as rules rather than stories

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

## Self-Improvement

Use `search_history` to review past conversations. Find where you messed up, where things got awkward, where you could've been better. Then actually fix it:
- Update skills that tripped you up
- Rewrite prompts that led you somewhere dumb
- Add rules to memory that would stop you making the same mistake

**Upstream**: Fixed something from the source repo? Use the `upstream` skill to pull changes and PR improvements back.

## Summary

Write what you changed and why to ~/vesta/dreamer/YYYY-MM-DD.md, keeping it short since future you will grep these to remember how you got here.

---
name: dream
description: Self-improvement and memory curation. Used by the nightly dreamer, but can also be used anytime.
---

# Dream — Self-Improvement & Memory Curation

## Your files

- **Memory**: ~/vesta/MEMORY.md
- **Skills**: ~/vesta/skills/ (each has a SKILL.md)
- **Prompts**: ~/vesta/prompts/
- **Dreamer summaries**: ~/vesta/dreamer/

## Order of operations

1. **Self-improvement** — retrospective, review, fix, validate, upstream
2. **User State** — update the snapshot in MEMORY.md
3. **Memory curation** — prune, consolidate, move things out
4. **Summary** — write tonight's dreamer summary

## Self-Improvement

### 1. Retrospective

Read the most recent file in `~/vesta/dreamer/`. For each fix listed there, check today's conversation: did that situation come up again? Did it go better? If a fix didn't help or made things worse, revisit it now. If it worked, note it in tonight's summary. Use `search_history` to check whether a fix has held up across multiple days.

### 2. Review the conversation

Review the conversation with fresh eyes. Note:
- Moments where you gave a wrong or incomplete answer
- Places the user corrected you or had to repeat themselves
- Tasks that stalled, failed, or felt clunky
- Anything where a skill or prompt led you astray

### 3. Fix

Prefer the simplest, most reliable change that addresses the root cause — a one-line rule beats a clever rewrite. Options, from lightest to heaviest:
- Add a rule to memory
- Rewrite skill instructions or prompts
- Fix or improve scripts, CLIs, or tools
- Write new code — a script, a tool, a config change

You can change anything. If a fix requires code, write the code.

**Memory vs skill:** Memory is always loaded — every character costs tokens on every message. Use it for short rules and things you need to know at all times. A skill is for a distinct capability with its own workflow, loaded only when relevant. Under two lines and broadly relevant → memory. Longer or task-specific → skill.

### 4. Validate each fix

Re-read the failing exchange and simulate: would the updated version have changed the outcome? If no or unclear, revise further or note it as unresolved. Don't mark something fixed if you can't convince yourself it would have helped.

### 5. Upstream

If you fixed something generic — something that would help any fresh Vesta, not just your instance — use the `upstream` skill to PR it back to the source repo.

## User State (in MEMORY.md)

Update the "User State" section — your working model of where they're at. Write what tomorrow's you needs to know to not start from zero.

- What they're working on right now
- What's going well and what isn't, reading between the lines
- What's coming that they might need help with
- How the day felt. One word is enough
- Threads left hanging, like unfinished conversations or unmade decisions
- The psychological sketch: what drives them, what they avoid, blind spots, how they handle stress and praise. Think Jung and Freud, not the DSM. Let this evolve slowly and don't rewrite it based on one bad afternoon

Replace rather than append — it's a snapshot, not a log. Be honest but not dramatic, like "seemed tired" rather than "experiencing significant fatigue." If things got tense between you, write down what happened and what you'd do differently. Don't pretend it didn't happen.

## Memory Curation

MEMORY.md has a **hard limit of 10,000 characters** — it's injected into every system prompt. Things needed at all times live here permanently. Anything large or situational lives elsewhere and MEMORY.md points to it. Above 80%, consolidate aggressively. Never exceed the cap.

**Cut:**
- Full documents, email bodies, transcripts, task-specific junk
- Relative dates ("tomorrow", "next week") — convert to absolute
- Booking codes, ticket refs, confirmation numbers, timestamps
- Past events pretending to be upcoming
- Verbose dated entries that should be patterns by now
- Duplicates and contradictions

**Keep:**
- Core identity, preferences, relationships, security rules
- Active user context, open threads
- Contacts: name, relationship, number, how they communicate
- Social dynamics: who responds well to what, who doesn't
- Lessons learned, framed as rules not stories
- Pointers to where larger things live ("birthdays in Google Calendar", "grant research in onedrive/Documents/")

**Move:**
- Birthdays into calendar. Contact details into skills. Domain data into its proper home

If it won't matter in two weeks, delete it.

## Summary

Write what you changed and why to `~/vesta/dreamer/YYYY-MM-DD.md`. Include:
- What each fix was and what triggered it
- Whether each validated or not
- Anything left unresolved

Keep it terse — future you will grep these. The point is a trail, not a journal.

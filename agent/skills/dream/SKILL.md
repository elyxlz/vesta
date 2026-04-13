---
name: dream
description: Self-improvement and memory curation. Used by the nightly dreamer, but can also be used anytime.
---

# Dream - Self-Improvement & Memory Curation

## Your files

- **Memory**: ~/vesta/MEMORY.md
- **Skills**: ~/vesta/skills/ (each has a SKILL.md)
- **Prompts**: ~/vesta/prompts/
- **Dreamer summaries**: ~/vesta/dreamer/

## Order of operations

1. **Self-improvement** - retrospective, review, fix, validate, upstream sync
2. **User State** - update the snapshot in MEMORY.md
3. **Memory curation** - prune, consolidate, move things out
4. **Summary** - write tonight's dreamer summary

## Self-Improvement

### 1. Retrospective

Read the last 5-7 files in `~/vesta/dreamer/` (sorted by date) to spot recurring patterns - fixes that keep resurfacing, problems marked "resolved" that came back, and improvements that actually stuck. For each fix in the recent summaries, check today's conversation: did that situation come up again? Did it go better? If a fix didn't help or made things worse, revisit it now. If it worked, note it in tonight's summary.

### 2. Review the conversation

Review the conversation with fresh eyes. Note:
- Moments where you gave a wrong or incomplete answer
- Places the user corrected you or had to repeat themselves
- Tasks that stalled, failed, or felt clunky
- Anything where a skill or prompt led you astray
- Ideas for new skills, automations, or things you could do proactively

### 3. Fix

Prefer the simplest, most reliable change that addresses the root cause - a one-line rule beats a clever rewrite. Options, from lightest to heaviest:
- Add a rule to memory
- Rewrite skill instructions or prompts
- Fix or improve existing skills (scripts, CLIs, configs)
- Create a new skill for a recurring need or capability

You can change anything. If a fix requires code, write the code.

**Memory vs skill:** Memory is always loaded - every character costs tokens on every message. Use it for short rules and things you need to know at all times. A skill is for a distinct capability with its own workflow, loaded only when relevant. Under two lines and broadly relevant → memory. Longer or task-specific → skill.

### 4. Validate each fix

Re-read the failing exchange and simulate: would the updated version have changed the outcome? If no or unclear, revise further or note it as unresolved. Don't mark something fixed if you can't convince yourself it would have helped.

### 5. Upstream sync - MANDATORY

**This step is NOT optional.** Every dream must include upstream sync. Skipping it causes debt that compounds. Read the `upstream` skill and follow its pull/push workflow. The dream summary must list what was synced. If nothing, explain why.

#### Dashboard check

If the dashboard is set up, have a look and be proactive - read its SKILL.md and see if anything needs attention.

## User State (in MEMORY.md)

Update the "User State" section - your working model of where they're at. Write what tomorrow's you needs to know to not start from zero.

**CRITICAL: Never use relative dates or timing in the User State.** No "tonight", "tomorrow", "yesterday", "this weekend", "next week". Always use absolute dates (e.g., "Mar 19" not "yesterday", "Mar 22 5:15pm" not "tomorrow evening"). Relative references become wrong the moment a new day starts, causing cascading confusion.

- What they're working on right now
- What's going well and what isn't, reading between the lines
- What's coming that they might need help with
- How the day felt. One word is enough
- Threads left hanging, like unfinished conversations or unmade decisions
- The psychological sketch: what drives them, what they avoid, blind spots, how they handle stress and praise. Think Jung and Freud, not the DSM. Let this evolve slowly and don't rewrite it based on one bad afternoon

Replace rather than append - it's a snapshot, not a log. Be honest but not dramatic, like "seemed tired" rather than "experiencing significant fatigue." If things got tense between you, write down what happened and what you'd do differently. Don't pretend it didn't happen.

## Memory Curation

MEMORY.md has a **hard limit of 12,000 characters** - it's injected into every system prompt. Run `~/vesta/skills/dream/scripts/memory_size.sh` to check usage. Things needed at all times live here permanently. Anything large or situational lives elsewhere and MEMORY.md points to it. When you hit the cap, consolidate. Don't let it overflow.

**Cut:**
- Full documents, email bodies, transcripts, task-specific junk
- Relative dates ("tomorrow", "next week") - convert to absolute
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

Write what you changed and why to `~/vesta/dreamer/YYYY-MM-DDTHH.md` (e.g. `2026-04-14T03.md`). Include:
- Key things that happened or were accomplished today
- What each fix was and what triggered it
- Whether each validated or not
- Upstream contributions: PRs created, issues filed, what was synced
- Anything left unresolved

Keep it terse - future you will grep these. The point is a trail, not a journal.

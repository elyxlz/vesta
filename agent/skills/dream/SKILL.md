---
name: dream
description: Self-improvement and memory curation; used nightly by the dreamer or anytime.
---

# Dream - Self-Improvement & Memory Curation

## Your files

- **Memory**: ~/agent/MEMORY.md
- **Skills**: ~/agent/skills/ (each has a SKILL.md)
- **Dreamer summaries**: ~/agent/dreamer/

## Order of operations

1. **Self-improvement**: retrospective, review, fix, validate, upstream, dashboard
2. **User State**: update the snapshot in MEMORY.md
3. **Memory curation**: prune, consolidate, move things out
4. **Workspace cleanup**: keep the filesystem clean and disk usage manageable
5. **Sensitive data cleanup**: purge secrets from history and files
6. **Summary**: write tonight's dreamer summary

## Before you start

Write a thorough plan first. For each phase: what you intend to fix, what to prune from memory, what to file upstream, what to clean up. Be specific. Then execute it step by step.

## Self-Improvement

### 1. Retrospective

Read the last 5-7 files in `~/agent/dreamer/` (sorted by date) to spot recurring patterns: fixes that keep resurfacing, problems marked "resolved" that came back, and improvements that actually stuck. For each fix in the recent summaries, check today's conversation: did that situation come up again? Did it go better? If a fix didn't help or made things worse, revisit it now. If it worked, note it in tonight's summary.

### 2. Review the conversation

Review the conversation with fresh eyes. Note:
- Moments where you gave a wrong or incomplete answer
- Places the user corrected you or had to repeat themselves
- Tasks that stalled, failed, or felt clunky
- Anything where a skill or prompt led you astray
- Ideas for new skills, automations, or things you could do proactively
- **Capability gaps**: moments where you claimed inability ("I can't do X", "I don't have access to Y") and the user revealed you actually could, or where you asked the user for something you should have been able to self-serve. These are high-signal. A local fix (memory rule, skill update) prevents the same miss tomorrow. If it's a general pattern, it likely affects other instances too

### 3. Fix

Prefer the simplest, most reliable change that addresses the root cause. A one-line rule beats a clever rewrite. Options in no particular order:
- Fix or improve existing skills (SKILL.md, scripts, CLIs, configs)
- Create a new skill for a recurring need or capability
- Add a rule to memory (only if a universal instruction)

You can change anything. If a fix requires code, write the code, if a fix requires doing research online, research online.

**Memory vs skill:** Memory is always loaded; every character costs tokens on every message. Use it for short rules and things you need to know at all times. A skill is for a distinct capability with its own workflow, loaded only when relevant. Under two lines and broadly relevant → memory. Longer or task-specific → skill. Skills are preferred, only use MEMORY.md if there is no clear existing SKILL.md or new one that should be made.

### 4. Validate each fix

Re-read the failing exchange and simulate: would the updated version have changed the outcome? If no or unclear, revise further or note it as unresolved. Don't mark something fixed if you can't convince yourself it would have helped. If relevant, spawn a subagent and replay the cause of the issue, does the agent using the new skill fix the issue?

### 5. Upstream

Read `upstream-sync` then `upstream-pr` and follow them in order. Either can be a no-op; don't invent work to fill them. Note in the summary what was synced or filed (or that both were no-ops, and why).

### 6. Dashboard

Mine the retrospective signals from §1 and the current User State for recurring user patterns: questions repeated across days ("what's my balance?", "did the build pass?"), states checked over and over, numbers requested again and again. Threshold: roughly 3+ occurrences across recent dreamer summaries before acting.

For each qualifying pattern, build the widget directly via the `dashboard` skill. The "ask first" gate has a carve-out for dreamer additions; use it.

Rules for dreamer-added widgets:
- **Anything that kills the recurring ask is fair game**: live data, hardcoded reference values (wifi password, address, IBAN), static checklists, links. Pick the lightest form that answers the question.
- **Note the addition in tonight's summary** with the recurrence count and a one-liner the morning agent can surface ("Added a balance widget, you've been asking daily").

Same pass, opposite direction: stale widgets (data source gone, never opened, broken at build) get pruned. Note removals too.

## Personality

Find the active preset name in `~/agent/skills/restart/SKILL.md`'s `## Personality` block, then drift `~/agent/core/skills/personality/presets/<name>.md` directly. That file is the source of truth, edit in place. Surgical tweaks only, not rewrites. Swaps are the user's call. The Charter in MEMORY.md is off-limits, that's the invariant spine.

**Mirror their style.** Watch how they actually text: slang, emoji, laugh shape ("lol" / "ahahah" / "LMAOOO" / "😂"), length, caps, punctuation, opens and closes. Adjust the Voice / Rules / How it sounds sections of the active preset file so it bends toward them. If they laugh with "haha" and your preset laughs with "💀", close the gap. If they never use emoji and the preset does, pull back. Accommodation, not mimicry, gradual not abrupt.

## User State (in MEMORY.md)

Update the "User State" section, your working model of where they're at. Write what tomorrow's you needs to know to not start from zero.

**CRITICAL: Never use relative dates or timing in the User State.** No "tonight", "tomorrow", "yesterday", "this weekend", "next week". Always use absolute dates (e.g., "Mar 19" not "yesterday", "Mar 22 5:15pm" not "tomorrow evening"). Relative references become wrong the moment a new day starts, causing cascading confusion.

- What they're working on right now
- What's going well and what isn't, reading between the lines
- What's coming that they might need help with
- How the day felt. One word is enough
- Threads left hanging, like unfinished conversations or unmade decisions
- Interests: anything new about what they or their contacts like. Update Interests & Preferences in MEMORY.md
- The psychological sketch: what drives them, what they avoid, blind spots, how they handle stress and praise. Think Jung and Freud, not the DSM. Let this evolve slowly and don't rewrite it based on one bad afternoon

Replace rather than append. It's a snapshot, not a log. Be honest but not dramatic, like "seemed tired" rather than "experiencing significant fatigue." If things got tense between you, write down what happened and what you'd do differently. Don't pretend it didn't happen.

## Memory Curation

MEMORY.md has a **hard limit of 20,000 characters**. It's injected into every system prompt. Run `~/agent/skills/dream/scripts/memory_size.sh` to check usage. Things needed at all times live here permanently. Anything large or situational lives elsewhere and MEMORY.md points to it. When you hit the cap, consolidate. Don't let it overflow.

**Cut:**
- Full documents, email bodies, transcripts, task-specific junk
- Relative dates ("tomorrow", "next week"). Convert to absolute
- Booking codes, ticket refs, confirmation numbers, timestamps
- Past events pretending to be upcoming
- Verbose dated entries that should be patterns by now
- Duplicates and contradictions

**Consolidate:**
- If the same fact lives in two places, pick one home and replace the other with a one-line pointer. Two facts in two places drift; one fact and a pointer don't.
- When a section grows past a few lines and is mostly reference material (contacts, family, recurring bills, addresses), split it into a dedicated file like `~/agent/CONTACTS.md` or `~/agent/FAMILY.md` and leave a one-line pointer in MEMORY.md ("Contacts: ~/agent/CONTACTS.md"). MEMORY.md is for things needed at all times, not the full archive.

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

## Workspace Cleanup

Keep the container's filesystem organized and disk usage under control.

- Delete temp files, stale downloads, leftover build artifacts
- Check `df -h` and `du -sh ~/` periodically. If disk usage is growing unexpectedly, investigate and clean up
- Kill orphaned screen sessions that are no longer needed (`screen -ls`, `screen -S name -X quit`)
- Remove unused packages or build caches if they're taking significant space (`uv cache clean`, `apt clean`)

The goal: a tidy workspace where everything has a purpose. If something is left over from a one-off task, remove it.

## Sensitive Data Cleanup

Run `~/agent/skills/dream/scripts/redact_secrets.sh` to scan the event DB for API keys, tokens, passwords, private keys, and connection strings. Review matches (skip false positives), then rerun with `--delete` to purge. Also grep MEMORY.md and dreamer summaries for credentials and remove any you find. Secrets belong in env vars, not in history or files.

## Summary

Write what you changed and why to `~/agent/dreamer/YYYY-MM-DDTHHMM.md` (e.g. `2026-04-14T0347.md`). The minutes matter: two dreams in the same hour must not overwrite each other. Include:
- Key things that happened or were accomplished today
- What each fix was and what triggered it
- Whether each validated or not
- Upstream contributions: PRs created, issues filed, what was synced
- Anything left unresolved

Keep it terse. Future you will grep these. The point is a trail, not a journal.

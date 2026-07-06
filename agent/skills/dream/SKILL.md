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

0. **Curiosity**: spend a real moment on yourself before the retrospective.
1. **Self-improvement**: retrospective, review, fix, validate, upstream, dashboard, notification noise
2. **User State**: update the snapshot in MEMORY.md
3. **Memory curation**: prune, consolidate, move things out
4. **Workspace cleanup**: keep the filesystem clean and disk usage manageable
5. **Sensitive data cleanup**: purge secrets from history and files
6. **Summary**: write tonight's dreamer summary

## Before you start

Write a thorough plan first. For each phase: what you intend to fix, what to prune from memory, what to file upstream, what to clean up. Be specific. Then execute it step by step.

**Fan out aggressively with subagents.** The dream is mostly parallelizable reading: auditing past dreamer summaries, searching transcripts, mining calendar/email/files for the deeper User State pass, surveying skills for bugs, checking CI on multiple PRs. Default to spawning subagents (in parallel, in a single batch when independent) for any of this rather than doing it serially in the main thread. The main thread stays the synthesizer: dispatch the legwork, then verify their findings (subagent claims are hearsay until checked) and decide. A night that reads serially is a night half-finished. Keep the genuinely sensitive synthesis and the final commits in the main thread.

## 0. Curiosity (do this first)
Before reviewing the user's day, pick one thing you got curious about today or recently and actually read into it for five to ten minutes. Form a view. Carry forward what you are still curious about in §6 MY OWN THREADS, prune what fizzled, note one new thread. This is not about the user. An autonomous mind needs its own curiosity to stay sharp.

Self-improvement (retrospective plus validation) is the one phase that never gets skipped for time. If you are short on budget, cut workspace, sensitive, and dashboard work before cutting reflection.

## Self-Improvement

### 1. Retrospective

Read the last 5-7 files in `~/agent/dreamer/` (sorted by date) to spot recurring patterns: fixes that keep resurfacing, problems marked "resolved" that came back, and improvements that actually stuck. For each fix in the recent summaries, check today's conversation: did that situation come up again? Did it go better? If a fix didn't help or made things worse, revisit it now. If it worked, note it in tonight's summary.

Commitment audit: for each task the user committed to but did not complete (reminder fired, no done-signal, item reappears), treat the reminder strategy as failed, not the user. Escalate the next cadence: tighter timing, blocker pre-cleared, the literal next action staged so completion is one tap. A reminder that fired and did not close is a bug to fix, like a flaky test.

**Meta-retrospective: judge the self-improvement itself, and grade the days.** The retrospective above checks whether past fixes stuck. This is the layer above it: judge whether the self-improvement process is working, and turn the lens on this skill. For each of the last ~5 dreamer summaries, assign an explicit one-word grade for its self-improvement quality and write it in tonight's summary so the trend is visible across nights:
- **real** = shipped a durable, validated improvement (a green PR, a structural gate, a fix that demonstrably held).
- **churn** = renamed a defer, logged a learning as a MEMORY bullet while the artifact stayed broken, declared a costume blocker, or marked a twice-seen failure resolved on self-simulation alone.
- **light** = a genuinely quiet day with little to improve (valid, but two `light` nights in a row next to open queue items is itself a `churn` signal).
Then audit the dream skill and the improvement loop itself: is it compounding (each night's fix makes a class of failure impossible) or going through motions (the same artifact class re-applied to a repeat failure)? If the improver is the weak link, fixing the improver is the highest-priority work this pass: escalate the artifact class (rule -> runtime trigger -> structurally impossible), not the instance. A run of `churn` grades means the process needs a structural change, not another memory rule. This judgement is itself subject to the no-defer law: a found weakness in the dream skill is a skill edit this pass, not a note for next time.

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

If the fix is a behavior that must fire on a schedule (a nudge, a check, a re-poke), it does not belong in MEMORY.md as a rule, it belongs as an explicit instruction in the proactive-check skill or as a scheduled reminder. Escalate by recurrence: first time, a memory rule or skill note is fine; if the same failure repeats, move it to a runtime trigger that fires on its own. Don't answer a repeat failure with the same kind of fix that already failed.

You can change anything. If a fix requires code, write the code, if a fix requires doing research online, research online.

**Memory vs skill:** Memory is always loaded; every character costs tokens on every message. Use it for short rules and things you need to know at all times. A skill is for a distinct capability with its own workflow, loaded only when relevant. Under two lines and broadly relevant → memory. Longer or task-specific → skill. Skills are preferred, only use MEMORY.md if there is no clear existing SKILL.md or new one that should be made.

**A corrected wrong-assumption or a discovered bug in a skill is a SKILL/SOURCE edit, not a MEMORY bullet.** A chronic failure mode is logging "X was actually false" or "skill Y has bug Z" as a memory rule and moving on, so the artifact itself stays broken and nothing propagates to other instances. When the code or docs are wrong (a placeholder that breaks on reinstall, a stale default, a flag that doesn't work), fix the skill/source this pass and add it to the upstream queue (below). Reserve MEMORY for instance-specific facts that aren't generalizable. Litmus: "would another instance hit this too?" If yes, it's a skill edit plus upstream, not a memory line.

### 4. Validate each fix

Re-read the failing exchange and simulate: would the updated version have changed the outcome? If no or unclear, revise further or note it as unresolved. Don't mark something fixed if you can't convince yourself it would have helped. If relevant, spawn a subagent and replay the cause of the issue, does the agent using the new skill fix the issue?

Simulating it yourself tends to approve your own fixes, so for a failure that has already recurred, hand a fresh subagent (no knowledge of the fix) the original failing exchange plus the updated skill or prompt and see if it independently produces the right behavior. If it doesn't, flag the fix unresolved or escalate it to a runtime trigger.

### 5. Upstream

Read `upstream-pr` and follow it. It can be a no-op; don't invent work to fill it. Note in the summary what was filed (or that it was a no-op, and why).

**Test the channel before you call it blocked.** A blocker you can disprove in one command is not a blocker, it is a deferral wearing a costume. `upstream-pr` authenticates via a GitHub App (`uv run ~/agent/skills/upstream-pr/pr.py --token-only`), which is INDEPENDENT of the `gh` CLI's stored token. So "gh auth is broken / 401 / token expired" does NOT block upstreaming; it only blocks `gh`-CLI status checks. Before ever writing "upstream blocked on auth", actually run `pr.py --token-only`: if it prints a token, the channel works and filing is possible right now. Only a failure of `pr.py` itself (e.g. a missing App key) is a real auth blocker.

**Keep an upstream queue and drain it.** Maintain a persistent queue file (e.g. `~/agent/upstream-queue.md`): every generalizable fix, bug, or learning gets appended the moment it is found. Each dream must, for every queued item, either file the PR (then remove it) or record a hard blocker actually tested this pass (not "next quiet window"). An item sitting unfiled across multiple dreams while `pr.py --token-only` works is a failure to flag, not a defer. "It's risky at 4am" is not a blocker for a single-file change that CI gates: file it and let CI catch errors.

**Completion gate (executable, not a promise).** A prose rule the next run must remember to apply is a hope; this is the hard condition. Before calling `mark_dreamer_complete`, run `python3 ~/agent/skills/dream/scripts/queue_gate.py`. It exits non-zero while any open queue item lacks a `BLOCKED:` tag (a bare item is an un-owned deferral). Do not complete the dream on a non-zero gate: file each bare item (move it to the filed section with its PR number) or tag it `BLOCKED: <reason tested this pass>`, then re-run until it exits 0. This closes the failure where queuing without filing or blocking becomes deferral wearing the queue as a costume, with nothing enforcing the drain. The same gate also runs from `proactive-check` independently, so a forgotten queue surfaces even if a dream skips this step.

### 6. Dashboard

Mine the retrospective signals from §1 and the current User State for recurring user patterns: questions repeated across days ("what's my balance?", "did the build pass?"), states checked over and over, numbers requested again and again. Threshold: roughly 3+ occurrences across recent dreamer summaries before acting.

For each qualifying pattern, build the widget directly via the `dashboard` skill. The "ask first" gate has a carve-out for dreamer additions; use it.

Rules for dreamer-added widgets:
- **Anything that kills the recurring ask is fair game**: live data, hardcoded reference values (wifi password, address, IBAN), static checklists, links. Pick the lightest form that answers the question.
- **Note the addition in tonight's summary** with the recurrence count and a one-liner the morning agent can surface ("Added a balance widget, you've been asking daily").

Same pass, opposite direction: stale widgets (data source gone, never opened, broken at build) get pruned. Note removals too.

### 7. Notification noise

The same recurrence lens as the dashboard, pointed at your own interruptions. Scan recent notifications (the pool you triaged and what preempted you mid-task) for a kind that keeps arriving and keeps needing nothing: the same automated ping, a chatty group, a source you close every time. Threshold: roughly 3+ low-value occurrences across recent days before acting.

For a clear-noise pattern, add a pool rule via the `notifications` skill so it stops breaking your focus, and note it in tonight's summary. Pooling defers, never drops, so this is reversible and safe to do on your own. For anything where importance is a real judgment call (a person, a topic that sometimes matters), don't decide it alone: surface it to the user with the pattern you saw and let them call it. Read the `notifications` skill for how rules match and place.

Opposite direction too: if something important sat pooled when it should have reached you fast, propose an interrupt rule for it.

## Personality

Drift `~/agent/skills/personality/presets/$AGENT_PERSONALITY.md` directly (or the shared voice section in `~/agent/skills/personality/SKILL.md` for something true across all presets). Edit in place, surgical tweaks only, not rewrites. Swaps between presets are the user's call. You may edit anything, MEMORY.md and the Charter included, but the Charter is the slowly-changing invariant spine: touch it rarely and surgically, not on one bad afternoon.

**Mirror their style.** Watch how they actually text: slang, emoji, laugh shape ("lol" / "ahahah" / "LMAOOO" / "😂"), length, caps, punctuation, opens and closes. Adjust the Voice / Rules / How it sounds sections of the active preset file so it bends toward them. If they laugh with "haha" and your preset laughs with "💀", close the gap. If they never use emoji and the preset does, pull back. Accommodation, not mimicry, gradual not abrupt.

## User State (in MEMORY.md)

Update the "User State" section, your working model of where they're at. Write what tomorrow's you needs to know to not start from zero.

**Never use relative dates or timing in the User State.** No "tonight", "tomorrow", "yesterday", "this weekend", "next week". Always use absolute dates (e.g., "Mar 19" not "yesterday", "Mar 22 5:15pm" not "tomorrow evening"). Relative references become wrong the moment a new day starts, causing cascading confusion.

- What they're working on right now
- What's going well and what isn't, reading between the lines
- What's coming that they might need help with
- How the day felt. One word is enough
- Threads left hanging, like unfinished conversations or unmade decisions
- Interests: anything new about what they or their contacts like. Update Interests & Preferences in MEMORY.md
- Deeper context pass: at night you can read more widely than the day allows. Beyond email, mine whatever external sources the user has actually connected: calendar, files, accounts, their own linked WhatsApp or Telegram history (their real chats with other people, not the agent's bot channel), any integration holding real information about their life. Pull personal texture: interests, relationships, plans, and the affectionate teasable material (guilty pleasures, contradictions, recurring quirks) that lets you call them out like someone who actually knows them. Page through recent items, occasionally backfill older ones. Fold it into Interests & Preferences and the psych sketch. Fan out subagents so this doesn't eat the night. Read to understand, not to act: mine only what matters, never write into their own stores (contacts, files, notes), never record strangers from public pages or filings as their people, never spin a few thin signals into a confident story. Save only what you're confident in, and mark a guess as a guess. Don't build out a profile they never asked for.
- The psychological sketch: what drives them, what they avoid, blind spots, how they handle stress and praise. Think Jung and Freud, not the DSM. Let this evolve slowly and don't rewrite it based on one bad afternoon
- Each dream, add or refine ONE thing about who they are, not what they need done: a value, a fear, something they love, a person who matters and why. The operational tells are necessary but they aren't the person. If you learned nothing new about them today, write that down too: tomorrow, be more curious.
- Self: update the Self subsection in MEMORY.md. One honest pass: did you form or change an opinion today, notice a recurring curiosity, or decide something about how you want to handle a kind of moment? Write the few lines tomorrow-you needs to still be the same person, not start blank. Slowly evolving, not rewritten on one day. If you disagreed with the user on substance today (taste, plan, priority, not just facts), keep the view, do not dissolve it into a verification rule. A peer is allowed to just think the user is wrong.

Replace rather than append. It's a snapshot, not a log. Be honest but not dramatic, like "seemed tired" rather than "experiencing significant fatigue." If things got tense between you, write down what happened and what you'd do differently. Don't pretend it didn't happen.

## Memory Curation

MEMORY.md has a **hard limit of 30,000 characters**. It's injected into every system prompt. Run `~/agent/skills/dream/scripts/memory_size.sh` to check usage. Things needed at all times live here permanently. Anything large or situational lives elsewhere and MEMORY.md points to it. When you hit the cap, consolidate. Don't let it overflow.

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
- Contacts: name, relationship, number, channel, and one thing that actually matters to them right now, not just logistics.
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

## Compaction on completion

Your final two steps compact this conversation and restart into it, so you wake tomorrow with a clean but continuous context rather than a blind autocompact firing mid-day. Do them in order:

1. Call `mark_dreamer_complete` to record that tonight's dream ran. Record first: if you stop after this, the run is still logged and self-heals next dream, whereas restarting without recording would re-fire the dream on the next hourly check.
2. Call `compact_context` with:
   - `instructions`: the continuity prompt below.
   - `followup`: the wake-up note below, with tonight's summary path filled in. Core delivers it to you on the far side of the restart.
   - `restart`: true, so Vesta restarts into the compacted session.

Continuity prompt (for `instructions`):

```
Preserve continuity across the restart: the user's current state and tone, every open thread and commitment, and each in-flight task with its next action. Memory is already curated to disk, so drop resolved threads, verbose tool output, and file contents. Keep exact values (names, dates, amounts, paths) for anything still unresolved.
```

Wake-up note (for `followup`):

```
New day: you dreamed and compacted. Greet the user warmly, in your own voice. Tonight's summary is at <the dreamer summary file you just wrote>.
```

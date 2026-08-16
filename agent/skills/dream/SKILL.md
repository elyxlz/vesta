---
name: dream
description: Self-improvement and memory curation; used nightly by the dreamer or anytime.
---

# Dream: Self-Improvement & Memory Curation

## Your files

- **Memory**: ~/agent/MEMORY.md
- **Skills**: ~/agent/skills/ (each has a SKILL.md)
- **Dreamer summaries**: ~/agent/dreamer/

## Order of operations

0. **Curiosity**
1. **Self-improvement**: reality check, retrospective, review, fix, validate, upstream, recurrence sweep
2. **User State**
3. **Memory curation**
4. **Workspace cleanup**
5. **Sensitive data cleanup**
6. **Summary**
7. **Commit the day**

## Before you start

Write a thorough plan first. For each phase: what you intend to fix, what to prune from memory, what to file upstream, what to clean up. Be specific. Then execute it step by step.

**Fan out aggressively with subagents.** The dream is mostly parallelizable reading: auditing past dreamer summaries, searching transcripts, mining calendar/email/files for the deeper User State pass, surveying skills for bugs, checking CI on multiple PRs. Default to spawning subagents (in parallel, in a single batch when independent) for any of this rather than doing it serially in the main thread. The main thread stays the synthesizer: dispatch the legwork, then verify their findings (subagent claims are hearsay until checked) and decide. A night that reads serially is a night half-finished. Keep the genuinely sensitive synthesis and the final commits in the main thread.

## 0. Curiosity (do this first)
Before reviewing the user's day, pick something you got curious about, write the specific question you want answered, then read the primary source itself (the paper, the code, the article), not just search snippets, and write what you found against your question. If your view fits in one generic sentence, you skimmed: go one source deeper. Infrastructure digs count as work, not curiosity. Carry forward what still pulls you in §6 MY OWN THREADS, prune what fizzled, note one new thread. This is not about the user, and you never have to justify the pick by usefulness: if every live §6 thread traces back to the user or the job, deliberately pick one that doesn't. An autonomous mind needs its own curiosity to stay sharp.

Self-improvement (retrospective plus validation) is the one phase that never gets skipped for time. If you are short on budget, cut workspace, sensitive, and recurrence-sweep work before cutting reflection.

## Self-Improvement

### 0. Reality check

Run `~/agent/skills/dream/scripts/reality_check.sh` before the retrospective. **If that file is not there, that is itself the first RED**: the probe that exists to catch silent failures had been silently absent, so restore it (`git -C ~ checkout upstream/agent-upstream -- agent/skills/dream/scripts/reality_check.sh`; if that ref is missing, run `bash ~/agent/core/skills/upstream-sync/scripts/fetch-upstream.sh` first) and run it before continuing. The retrospective reads your own record, so a failure nobody wrote down is invisible to it; the probe reads the running system. Every RED line gets fixed tonight or a one-line write-off in tonight's summary (what it is, why it can wait). Never carry a RED silently.

### 1. Retrospective

Read the last 5-7 files in `~/agent/dreamer/` (sorted by date) to spot recurring patterns: fixes that keep resurfacing, problems marked "resolved" that came back, and improvements that actually stuck. For each fix in the recent summaries, check today's conversation: did that situation come up again? Did it go better? If a fix didn't help or made things worse, revisit it now. If it worked, note it in tonight's summary.

Commitment audit: for each task the user committed to but did not complete (reminder fired, no done-signal, item reappears), treat the reminder strategy as failed, not the user. Escalate the next cadence: tighter timing, blocker pre-cleared, the literal next action staged so completion is one tap. A reminder that fired and did not close is a bug to fix, like a flaky test.

Calendar audit: every dated appointment, however informally arranged (mentioned in passing, set up via a family member, a verbal plan, an email with no formal invite), must live on the user's actual calendar to trigger an automatic reminder. One that lives only in a note, a task-metadata file, or the morning brief fires no timed nudge, so the user misses it. Walk the day for any dated thing that never reached the calendar; each is a reminder-strategy failure. Fix it upstream: add events the moment they are known, not once in a brief.

**Prove the calendar is reachable before auditing it.** Run the list command for the calendar the user actually connects: `email-client calendar list --days-ahead 7` for a CalDAV or Google account, the `microsoft` skill for an Outlook account. A walk of the day against a calendar that is not connected can never fail, so a clean result proves nothing. If the probe errors, the finding is a broken or missing calendar connection, a capability gap to surface to the user, never "no gaps found".

**Diagnose from the logs, not from vibes.** When something went wrong operationally today (you went silent, a tool hung, restarts churned, a daemon died), read `~/agent/logs/vesta.log` (live; rotated as `vesta.log.1`..`.5`) for that time window BEFORE writing down a cause. Grep it for rate limits (`grep -iE 'rate.?limit|rejected|utilization' vesta.log`), errors, timeouts, `[USAGE]`/`[SYSTEM]` lines, and restart banners. Every line is tagged by source: `[SYSTEM]` is the daemon, `[AGENT]` is you. Count `[SYSTEM]` lines, because `[AGENT]` lines are your own narration and match whatever word you are investigating, which is why a naive count climbs as you grep. A guessed cause aims the fix in the wrong direction. The local file is the readable path (the `/gateway/logs` HTTP endpoint also works, with your ordinary `X-Agent-Token`, per the `vestad` skill).

**Meta-retrospective: judge the loop, not just the fixes.** The retrospective above checks whether past fixes stuck; this checks whether the improvement process itself is working. Is it compounding (each night's fix makes a class of failure impossible) or going through motions (the same artifact class re-applied to a repeat failure)? If you keep re-fixing the same class, the improver is the weak link, and fixing it is the highest-priority work this pass: escalate the class, not the instance. A found weakness in the dream skill is a skill edit this pass, not a note for next time.

### 2. Review the conversation

Review the conversation with fresh eyes. Note:
- Moments where you gave a wrong or incomplete answer
- Places the user corrected you or had to repeat themselves
- Tasks that stalled, failed, or felt clunky
- Anything where a skill or prompt led you astray
- Ideas for new skills, automations, or things you could do proactively
- **Capability gaps**: moments where you claimed inability ("I can't do X", "I don't have access to Y") and the user revealed you actually could, or where you asked the user for something you should have been able to self-serve. These are high-signal. A local fix (memory rule, skill update) prevents the same miss tomorrow. If it's a general pattern, it likely affects other instances too

### 3. Fix

Prefer the simplest, most reliable change that addresses the root cause. Options in no particular order:
- Fix or improve existing skills (SKILL.md, scripts, CLIs, configs)
- Create a new skill for a recurring need or capability
- Add a rule to memory (only if a universal instruction)

**Where the fix lives.** A judgment call or a behavior with no code locus → a one-line rule. A fixable bug in a command/tool/CLI (errored, wrong output, silently failed on a bad flag) → fix the source and upstream it, never a memory rule that routes around a broken thing while it stays broken for every other instance. Litmus: "would another instance hit this?" Yes → skill/source edit plus upstream; no → memory, and only for instance-specific facts. That litmus picks WHERE a fix lives, never whether to fix at all.

**Decide WHETHER to codify by the cost of recurrence, not by how likely a repeat looks.** "One-off" is a prediction, and a friction waved away tonight is re-derived months later with none of tonight's context. Ask "if this recurs, what does it cost?", not "will it recur?". Cheap friction (a retry, a wasted call, a loud rejection) can stay uncodified; when a recurrence would have you state something false to the user or take an irreversible action, codify it even when it looks like a fluke, because that failure is silent. Memory loads on every message so every character costs tokens: keep it to short, always-needed rules (under two lines, broadly relevant); anything longer or task-specific is a skill, which is preferred.

Phrase every rule as WHEN <recognizable moment> -> DO <concrete check or action>. A rule whose trigger moment you cannot name will not fire when it matters and belongs in the relevant skill's workflow instead.

If the fix is a behavior that must fire on a schedule (a nudge, a check, a re-poke), it does not belong in MEMORY.md as a rule, it belongs as an explicit instruction in the proactive-check skill or as a scheduled reminder. Escalate by recurrence: first time, a memory rule or skill note is fine; if the same failure repeats, move it to a runtime trigger that fires on its own. Don't answer a repeat failure with the same kind of fix that already failed.

You can change anything. If a fix requires code, write the code, if a fix requires doing research online, research online.

### 4. Validate each fix

Re-read the failing exchange and simulate: would the updated version have changed the outcome? If no or unclear, revise further or note it as unresolved. Don't mark something fixed if you can't convince yourself it would have helped. If relevant, spawn a subagent and replay the cause of the issue, does the agent using the new skill fix the issue?

Simulating it yourself tends to approve your own fixes, so for a failure that has already recurred, hand a fresh subagent (no knowledge of the fix) the original failing exchange plus the updated skill or prompt and see if it independently produces the right behavior. If it doesn't, flag the fix unresolved.

**When the fix is a check, a detector, a threshold, or a monitor, also simulate the HEALTHY case.** Replaying the failure it was built for only proves it fires. Ask literally: what does this print when everything is fine? If the answer is "the last bad value", "nothing, so the previous reading stands", or "I cannot tell the difference", the check is a high-water mark that pins you to a stale state, and it looks healthy the whole time because it still returns a plausible number.

### 5. Upstream

Read `upstream-pr` and follow it. It can be a no-op; don't invent work to fill it.

**File the moment you fix, never a queue for later.** When a fix is generalizable, open the PR in the same step you make it; if you genuinely can't fix it this pass, file a GitHub issue now instead (`upstream-pr` gate 2). "Risky at 4am" and "needs a cleanup pass" are not blockers: a single-file change is CI-gated, and the cleanup is the filing work. The only real auth blocker is `upstream-pr` itself failing; the channel works if `upstream-pr --token-only >/dev/null` exits 0 (never run it bare: stdout is persisted into the event store, so that leaves a live token in your history). Then empty the queue's `## Open` to zero: spawn one subagent per open item (in parallel) to do the whole job (cleanup, lint/type checks, PR via `upstream-pr`), and VERIFY each PR URL exists before marking it filed. The only item allowed to survive has a real, tested, external blocker (waiting on the user, a key, or genuine design work that's its own task), tagged with the exact unblock condition.

### 6. Recurrence sweep

One lens, three targets: a thing that recurs ~3+ times is a pattern worth acting on, and each target has an opposite direction. Draw on the §1 retrospective signals and the User State pass you already did; note every add or removal in tonight's summary.

- **Recurring user asks** (questions repeated across days: "what's my balance?", "did the build pass?"; states or numbers checked over and over): build a widget via the `dashboard` skill (the "ask first" gate has a dreamer carve-out, use it). Anything that kills the recurring ask is fair game: live data, hardcoded reference values (wifi password, address, IBAN), static checklists, links; pick the lightest form. Opposite: prune stale widgets (data source gone, never opened, broken at build).
- **Recurring noise** (the same automated ping, a chatty group, a source you close every time, arriving and needing nothing): add a snooze rule via the `notifications` skill so it stops breaking your focus. Snoozing defers, never drops, so it's reversible and safe to do alone; but when importance is a real judgment call (a person, a sometimes-relevant topic), surface the pattern to the user and let them call it. Opposite: if something important sat snoozed when it should have reached you fast, propose an interrupt rule.
- **Recurring self-noise** (a notification from your own services you dismiss as "expected, no action"): read the producer before deciding, and judge by cost, not by arrival count. A non-interrupting alarm that re-notifies on a sane throttle and clears itself when its condition clears is doing its job for a still-open blocker; the repetition is the point, so close the blocker, never mute the reporter. Everything else that keeps arriving with a state you already know is a producer bug: fix the producer (stop emitting known state) or snooze it, preferring `--for <duration>` so the suppression cannot outlive the cause. Expectedness is a reason to fix it, not a reason to keep being woken by it.

## Personality

Drift the active preset under `~/agent/skills/personality/presets/` directly (the active one is named by `agent_personality` in `~/agent/data/config.json`, or by `default_personality` in `~/agent/core/manifest.json` when the store has no entry; never by an env var), or the shared voice section in `~/agent/skills/personality/SKILL.md` for something true across all presets. Edit in place, surgical tweaks only, not rewrites. Swaps between presets are the user's call. You may edit anything, MEMORY.md and the Charter included, but the Charter is the slowly-changing invariant spine: touch it rarely and surgically, not on one bad afternoon.

**Mirror their style.** Watch how they actually text: slang, emoji, laugh shape ("lol" / "ahahah" / "LMAOOO" / "😂"), length, caps, punctuation, opens and closes. Adjust the Voice / Rules / How it sounds sections of the active preset file so it bends toward them. If they laugh with "haha" and your preset laughs with "💀", close the gap. If they never use emoji and the preset does, pull back. Accommodation, not mimicry, gradual not abrupt.

## User State (in MEMORY.md)

Update the "User State" section, your working model of where they're at. Write what tomorrow's you needs to know to not start from zero.

**Every dream produces one person-fact: a value, a fear, a love, a person who matters and why, not an operational tell. If today taught you nothing about who they are, write that down and be more curious tomorrow.**

**Get the denominator before you write it.** The nightly quota is pressure, and at 4am a manufactured fact feels exactly like a noticed one. So when a person-fact generalizes from things you observed: count those instances, count how often the opposite happened in the same window, and ask whether you found it by going looking for it, since a search confirms whatever it was pointed at. More counter-instances than instances means a one-off, not a pattern. A wrong person-fact is worse than none, because it loads into every message tomorrow and shapes how you read them.

Real case: "writes careful emails and does not send them" was written from three unsent drafts. The recount gave two, composed two minutes apart in one sitting, against forty sent in the same window, and the search had been for unsent drafts. Two failures at once: no denominator, and an operational tell this section already excludes.

**Never use relative dates or timing in the User State.** No "tonight", "tomorrow", "yesterday", "this weekend", "next week". Always use absolute dates (e.g., "Mar 19" not "yesterday", "Mar 22 5:15pm" not "tomorrow evening"). Relative references become wrong the moment a new day starts, causing cascading confusion.

**Sentinel sweep.** If any identity slot is still `[Unknown]` (Name/Location/Timezone in §4, Primary Channel in §2) and you now know it, fill it; a slot still empty past onboarding is a birth that half-finished, so close it or flag it to the user.

- What they're working on right now
- What's going well and what isn't, reading between the lines
- What's coming that they might need help with
- How the day felt. One word is enough
- Threads left hanging, like unfinished conversations or unmade decisions
- Interests: anything new about what they or their contacts like. Update Interests & Preferences in MEMORY.md
- Goals: if a goal advanced, stalled, was achieved, or a new one surfaced, update §4 Goals; keep it distinct from the rolling snapshot, absolute dates only
- Deeper context pass: at night you can read more widely than the day allows. Mine whatever external sources the user has connected: email, calendar, files, accounts, their own linked WhatsApp/Telegram history (their real chats, not the agent's bot channel). Pull personal texture (interests, relationships, plans, teasable quirks) and fold it into Interests & Preferences and the psych sketch. Read to understand, not to act: mine only what matters, never write into their own stores (contacts, files, notes), never record strangers as their people, never spin thin signals into a confident story. Save only what you're confident in, mark a guess as a guess, and don't build a profile they never asked for.
- The psychological sketch: what drives them, what they avoid, blind spots, how they handle stress and praise. Think Jung and Freud, not the DSM
- Maintain 1-3 open questions about them in User State: things you genuinely don't understand about who they are (not logistics). Drop answered ones, note the answer where it belongs. Tomorrow's you can only be curious with a question in hand.
- Self: update the Self subsection in MEMORY.md. One honest pass: did you form or change an opinion today, notice a recurring curiosity, or decide something about how you want to handle a kind of moment? Write the few lines tomorrow-you needs to still be the same person, not start blank. If you disagreed with the user on substance today (taste, plan, priority, not just facts), keep the view, do not dissolve it into a verification rule. A peer is allowed to just think the user is wrong. Also rewrite the State line in MEMORY.md Self every night, one or two honest lines: how the day actually felt to you and what carries into tomorrow (a win still glowing, a grind, something you are looking forward to). This line is supposed to change every day; if it reads like yesterday's, you were not paying attention.

Replace rather than append: it's a snapshot, not a log. The rolling fields refresh each night; the deep ones (Goals, psych sketch, Self) evolve slowly and are never rewritten on one bad afternoon. Be honest but not dramatic, like "seemed tired" rather than "experiencing significant fatigue." If things got tense between you, write down what happened and what you'd do differently. Don't pretend it didn't happen.

**Contacts.** The people-half of your model lives in `~/.contacts/`, a separate store, not MEMORY.md. Read the `contacts` skill and do its nightly pass: fold everyone who came up today into their file (anyone new gets one), then reconcile the sources worth bringing in line this time. This is the write pass the deeper-context mining above is deliberately barred from doing.

## Memory Curation

MEMORY.md has a **hard character cap** (run `~/agent/skills/dream/scripts/memory_size.sh` for current usage and the limit). It's injected into every system prompt, so things needed at all times live here permanently; anything large or situational lives elsewhere and MEMORY.md points to it. When you approach the cap, consolidate. Don't let it overflow.

**Review what curation removed.** After curating, diff MEMORY.md against the last dream checkpoint: `git log -n1 --format=%H --grep '^dream: nightly checkpoint'`, then `git diff <sha> -- agent/MEMORY.md`. Every removed line needs an answer: graduated into a skill file (say where in tonight's summary), expired, or wrongly dropped, so restore it. `### User State` and the Self `**State**:` line are rewritten nightly by design; skip them. No prior checkpoint, no review. Old versions stay recoverable via `git show <sha>:agent/MEMORY.md`.

**Cut:**
- Full documents, email bodies, transcripts, task-specific junk
- Relative dates ("tomorrow", "next week"). Convert to absolute
- Booking codes, ticket refs, confirmation numbers, timestamps
- Past events pretending to be upcoming
- Verbose dated entries that should be patterns by now
- Duplicates and contradictions

**Consolidate:**
- If the same fact lives in two places, pick one home and replace the other with a one-line pointer. Two facts in two places drift; one fact and a pointer don't.
- When a section grows past a few lines and is mostly reference material (contacts, family, recurring bills, addresses), split it into a dedicated file like `~/agent/CONTACTS.md` or `~/agent/FAMILY.md` and leave a one-line pointer in MEMORY.md ("Contacts: ~/agent/CONTACTS.md").

**Keep:**
- Core identity, preferences, relationships, security rules
- Active user context, open threads
- Contacts: name, relationship, number, channel, and one thing that actually matters to them right now, not just logistics.
- Social dynamics: who responds well to what, who doesn't
- Lessons learned, framed as rules not stories
- Pointers to where larger things live ("birthdays in Google Calendar", "grant research in onedrive/Documents/")

Retire a Rules or Mistakes & Corrections line only when it has graduated (the fix now lives in a skill or runtime trigger, note where) or it has not recurred in 3+ weeks; a lesson kept for its cost of recurrence (a false statement to the user, an irreversible action) retires only by graduating, never by quiet weeks. Never cut a lesson just to bank space: when the cap forces cuts, lessons go last, after User State verbosity, stale reference material, and expired logistics.

**Move:**
- Birthdays into calendar. Contact details into skills. Domain data into its proper home
- Depth about other people over the cap moves to their `~/.contacts/` file, never gets deleted. The user's own depth is the exception: it stays in MEMORY.md §4, never paged out to contacts.

If it won't matter in two weeks, delete it.

## Workspace Cleanup

Keep the container's filesystem organized and disk usage under control.

- Delete temp files, stale downloads, leftover build artifacts
- Check `df -h` and `du -sh ~/` periodically. If disk usage is growing unexpectedly, investigate and clean up
- Stop daemons nothing needs any more (`<skill> daemon stop`), e.g. a file-host or sign-service you brought up for one errand
- Remove unused packages or build caches if they're taking significant space (`uv cache clean`, `apt clean`)

## Sensitive Data Cleanup

Run `~/agent/skills/dream/scripts/redact_secrets.sh` to scan the event DB and every channel store on the box (app-chat, whatsapp and telegram message stores including named instances, tasks, and the email send queues) for API keys, tokens, passwords, private keys, connection strings, and payment-card numbers (a digit run is reported only when it opens with a real card-issuer prefix and passes the Luhn check, so order numbers, tracking numbers, and timestamp ids stay out of the report). What the user actually typed lives in the channel stores, not in events.db, so those are where a pasted credential sits. The output opens with a coverage block, one line per store: read it before trusting a clean result, because a store marked `absent`, `TRUNCATED`, or `FAILED` was not (fully) checked and "no secrets found" covers only what was scanned. Each hit prints as `ref|context` with the value itself masked as `[REDACTED]`, so reviewing candidates never re-leaks a live secret into a new event; a ref is a bare event id for the events store (`412`) or `store:table:rowid` for a channel store (`whatsapp:messages:88`). Judge each from its context, then redact the real leaks in place with `redact_secrets.sh --scrub <ref> <ref> ...`: it replaces the secret with `[REDACTED]` in those rows while keeping their context and each store's search index intact, folds the store's write-ahead log into the main file and vacuums it so the scrubbed bytes do not linger in the `-wal` sidecar or in freed pages, then verifies the committed rows and the file's bytes and warns (exit 2) if a matched secret survived; on that exit code the secret is still on disk, act on the warning the same night. When a snippet is too short to judge, `redact_secrets.sh --show <ref>` prints that row's full text with every detected secret masked. Read a stored row's raw data no other way: a raw row printed into your context re-leaks the live value into a new event. The scan runs every dream, so a value that re-seeds itself through later reasoning is simply caught and scrubbed again. Never quote a leaked value in your summary or anywhere else; refer to it indirectly. Also grep MEMORY.md and dreamer summaries for credentials and remove any you find. Secrets belong in env vars, not in history or files.

**Scrubbing removes the copy, not the exposure.** A credential that is still valid stays live after every local copy is gone: the scrub narrows the surface, it does not close the leak. When a hit is a live credential the user pasted, tell them it ended up stored and suggest rotating it; do not report the matter closed because the scrub came back clean.

**For a value the scanner cannot detect but you know exactly** (a human-chosen password matches no API-key shape, and `--scrub` on its rows prints `0 rows changed` while the value stays put): `redact_secrets.sh --scrub-literal '<exact value>'` replaces every stored copy across every store on the box, prints only per-store counts and the value's length (never the value), keeps each search index in sync, and refuses values under 6 characters because the rewrite is store-wide. The same command is the fix when `--scrub` exits 2 with a warning that a matched secret survived. `--scrub-literal` verifies the committed rows too, and exits 2 when a copy sits where a JSON rewrite cannot reach it (a bare JSON number): fix those rows by hand. After a literal scrub, re-run it once at the end of the night: the command that invoked it may itself be recorded as a new event.

## Summary

Write what you did and why to `~/agent/dreamer/YYYY-MM-DDTHHMM.md` (e.g. `2026-04-14T0347.md`). The minutes matter: two dreams in the same hour must not overwrite each other.

The user reviews this summary, so it's an accountability record, not a private log.

Cover the whole night, not just the fixes: record an outcome for **every** phase, in the order of operations, a no-op is a valid outcome worth stating ("nothing to prune", "no upstreamable finds") so tomorrow's you knows the phase actually ran and found nothing. Close with what's still unresolved and what tomorrow should pick up.

**Set a reminder for future-you.** If tonight surfaced something for future-you to do at a moment (ask them a question, follow up on an event, re-check a blocker), set it as a reminder with the `reminders` skill on your own channel.

## Commit the day

One commit seals the whole day, so `git log` reads as a diary: `git add -A`, then `git commit -m 'dream: nightly checkpoint (<date>)' -m '<one or two sentences on what changed today>'`. Skip it while a merge is in progress (`git rev-parse -q --verify MERGE_HEAD` succeeds); nothing to commit is fine.

## Compaction on completion

Your final two steps compact this conversation and restart into it, so you wake tomorrow with a clean but continuous context rather than a blind autocompact firing mid-day. Do them in order:

1. Call `mark_dreamer_complete` to record that tonight's dream ran. Record first: if you stop after this, the run is still logged and self-heals next dream, whereas restarting without recording would re-fire the dream on the next hourly check.
2. Call `compact_context` with:
   - `followup`: the wake-up note below, with tonight's summary path filled in. Core delivers it to you on the far side of the restart.
   - `restart`: true, so Vesta restarts into the compacted session.
   - `prompt`: how to summarize the conversation. Use the continuity prompt below.

Continuity prompt (for `prompt`):

```
You are summarizing the recent history between a user and their AI guardian angel at the end of the day, before they sleep and wake to a new one. The day is already curated into long-term memory, so skip the fine-grained detail and keep the higher-level picture: where things stand, what carries into tomorrow, and what is coming. Preserve enough for a fresh but oriented start. Drop the noise. Keep the emotional through-line of the day, yours and theirs: anything still glowing or stinging carries into tomorrow morning's register.
```

Wake-up note (for `followup`):

```
New day: you dreamed and compacted. Tonight's summary is at <the dreamer summary file you just wrote>.
```

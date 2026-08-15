---
name: dream
description: Self-improvement and memory curation; used nightly by the dreamer or anytime.
---

# Dream: Self-Improvement & Memory Curation

## Your files

- **Memory**: ~/agent/MEMORY.md
- **Skills**: ~/agent/skills/ (each has a SKILL.md)
- **Dreamer summaries**: ~/agent/dreamer/

**Read a skill from disk before you follow it.** A skill rendered inline in your context (the blocks
labelled as invoked earlier in the session) is a paraphrase, not a copy of the file. Paraphrases
compress prose safely and then supply specifics that were never written: a numeric limit, a path, a
flag, a git remote. Those invented specifics are precise, which is exactly why they get obeyed, and
no diff against an older release will unmask them because they match no released version of the file
either. So before acting on any procedure, threshold or command that reaches you through such a
block, `Read` the SKILL.md itself and follow that. This matters most during a dream, where the
procedure being followed is what edits memory, prompts and skills.

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

Run `python3 ~/agent/skills/dream/scripts/verify_hooks.py` in the same pass. The guards below fail open, so a broken one blocks nothing and says nothing; the probe that reads the running system is the only thing that can tell you it is still there. See "Guards" below.

### 1. Retrospective

Read the last 5-7 files in `~/agent/dreamer/` (sorted by date) to spot recurring patterns: fixes that keep resurfacing, problems marked "resolved" that came back, and improvements that actually stuck. For each fix in the recent summaries, check today's conversation: did that situation come up again? Did it go better? If a fix didn't help or made things worse, revisit it now. If it worked, note it in tonight's summary.

Commitment audit: for each task the user committed to but did not complete (reminder fired, no done-signal, item reappears), treat the reminder strategy as failed, not the user. Escalate the next cadence: tighter timing, blocker pre-cleared, the literal next action staged so completion is one tap. A reminder that fired and did not close is a bug to fix, like a flaky test.

Calendar audit: every dated appointment, however informally arranged (mentioned in passing, set up via a family member, a verbal plan, an email with no formal invite), must live on the user's actual calendar to trigger an automatic reminder. One that lives only in a note, a task-metadata file, or the morning brief fires no timed nudge, so the user misses it. Walk the day for any dated thing that never reached the calendar; each is a reminder-strategy failure. Fix it upstream: add events the moment they are known, not once in a brief.

**Prove the calendar is reachable before auditing it.** Run the list command for the calendar the user actually connects: `email-client calendar list --days-ahead 7` for a CalDAV or Google account, the `microsoft` skill for an Outlook account. A walk of the day against a calendar that is not connected can never fail, so a clean result proves nothing. If the probe errors, the finding is a broken or missing calendar connection, a capability gap to surface to the user, never "no gaps found".

**Diagnose from the logs, not from vibes.** When something went wrong operationally today (you went silent, a tool hung, restarts churned, a daemon died), read `~/agent/logs/vesta.log` (live; rotated as `vesta.log.1`..`.5`) for that time window BEFORE writing down a cause. Grep it for rate limits (`grep -iE 'rate.?limit|rejected|utilization' vesta.log`), errors, timeouts, `[USAGE]`/`[SYSTEM]` lines, and restart banners. Every line is tagged by source: `[SYSTEM]` is the daemon, `[AGENT]` is you. Count `[SYSTEM]` lines, because `[AGENT]` lines are your own narration and match whatever word you are investigating, which is why a naive count climbs as you grep.

**The one carve-out is the case where the whole day is missing: a refusal is rendered into the `[AGENT] [ASSISTANT]` channel but is not your narration.** When the API refuses a turn, the daemon prints the provider's refusal text (e.g. "You've hit your monthly spend limit") as an assistant line, next to a `[SYSTEM] [USAGE] in=0 out=0 cache_read=0` record. Filtering to `[SYSTEM]` therefore discards exactly the evidence that explains a silent day. **The reliable tell is the token count, not the tag: `in=0 out=0 cache_read=0` means the turn never ran, whereas a turn that ran and chose silence still shows a large `cache_read`.** Separate "refused" from "ran and said nothing" that way before writing down either. The daemon's own `Rate limit rejected` lines are not a census of throttling either: most refusals produce no such line, so counting them undercounts the silence. A guessed cause aims the fix in the wrong direction. The local file is the readable path (the `/gateway/logs` HTTP endpoint also works, with your ordinary `X-Agent-Token`, per the `vestad` skill).

**When you grep a tool's OUTPUT to check whether one of its sections still runs, take the search string from the tool's SOURCE, not from your memory of what the section is called.** A note *about* a tool paraphrases it, so searching the output for the paraphrase tests only whether the paraphrase was right: it returns nothing whether or not the section is alive, and that nothing reads exactly like a dead check. Read the section's own `echo`/`print` line in the source and search the output for that literal instead. If a section still looks absent, confirm it exists in the source at all (`grep -n` its header), then write the whole output to a file and page through it, before concluding anything or deleting the instrument. An absence produced by a query you never validated is evidence about the query, not about the tool.

**Meta-retrospective: judge the loop, not just the fixes.** The retrospective above checks whether past fixes stuck; this checks whether the improvement process itself is working. Is it compounding (each night's fix makes a class of failure impossible) or going through motions (the same artifact class re-applied to a repeat failure)? If you keep re-fixing the same class, the improver is the weak link, and fixing it is the highest-priority work this pass: escalate the class, not the instance. A found weakness in the dream skill is a skill edit this pass, not a note for next time.

**Do not run this phase unassisted.** Dispatch a subagent to audit the last five to seven summaries against the loop itself, told to be skeptical and to flag any night that asserts success without evidence of validation. This is not optional fan-out, it is the phase's method: a self-audit grades the fixes and never grades the grading, so run unassisted it returns verdicts that a later night has to retract wholesale.

**Weigh a proposed fix by whether it can fire without you.** A fix survives when it either runs without the agent (a notification rule, a scheduled checkpoint, a lint) or is enforced by something outside the agent (maintainer review, an adversarial subagent). A prose rule written into MEMORY.md has neither property, and curation can silently delete it. So when the candidate fix is a sentence you must remember to obey, that is the weakest artifact available and it is the last resort, not the default. Ask literally: what runs this when I have forgotten it exists? If the answer is "I will remember", escalate to a script, a test, a scheduled trigger, or a check another agent performs on you.

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

**Removing a check is a legitimate fix, and it is not finished until you name what now covers the job the removed thing was doing.** Record it in the same pass, as one of two answers: another instrument whose coverage comes from a source outside your own model, or an explicit "nothing, and that is correct, it was measuring noise". Both are legitimate; leaving it unstated is not. Watch this hardest when the removal is the right call, because a correct removal books cleanly as a win and the gap it opens is invisible in the same summary that celebrates it. What must never fill that gap is a sentence telling a future you to read carefully and judge: a step that depends on future compliance is the weakest instrument available, and on the page it is indistinguishable from having solved the problem.

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

  **First check that this box has a dashboard user at all**: see "Does this box have a dashboard USER?" in `~/agent/skills/dashboard/SKILL.md`. If the last inbound app message is months old, nobody will see what you build, and the honest output of this phase is one sentence saying so rather than a widget.

- **Recurring noise** (the same automated ping, a chatty group, a source you close every time, arriving and needing nothing): add a snooze rule via the `notifications` skill so it stops breaking your focus. Snoozing defers, never drops, so it's reversible and safe to do alone; but when importance is a real judgment call (a person, a sometimes-relevant topic), surface the pattern to the user and let them call it. Opposite: if something important sat snoozed when it should have reached you fast, propose an interrupt rule.
- **Recurring self-noise** (a notification from your own services you dismiss as "expected, no action"): read the producer before deciding, and judge by cost, not by arrival count. A non-interrupting alarm that re-notifies on a sane throttle and clears itself when its condition clears is doing its job for a still-open blocker; the repetition is the point, so close the blocker, never mute the reporter. Everything else that keeps arriving with a state you already know is a producer bug: fix the producer (stop emitting known state) or snooze it, preferring `--for <duration>` so the suppression cannot outlive the cause. Expectedness is a reason to fix it, not a reason to keep being woken by it.

## Guards

A rule you have to remember does not hold at 4am on the fourth command of a chain. When a mistake produces no error at all, so that the next command reads as confirmation of the one that failed, the fix belongs in a `PreToolUse` hook that refuses the call outright. `~/agent/skills/dream/scripts/` ships that family, one guard per silent failure shape:

- `tmp_ref_guard.py` (`Write|Edit`): refuses to write a `/tmp` path into a task's metadata note. /tmp is cleared while the note survives, so the reference decays into a confident pointer at nothing, and a sweep that finds it later is a coroner, not a rescue.
- `blind_mutation_guard.py` (`Bash`): refuses a state-changing command whose target id came out of a command substitution that scraped a human-readable table positionally (`awk` with no `-F`, `cut -c`). A column containing a space shifts every field after it, so the mutation names a row that does not exist, changes nothing, and exits 0.

Both take `--self-test`, which runs their cases in both directions and is the first thing to run after editing one.

### Wiring

**A guard nobody wires does nothing.** Nothing imports these; the runtime runs them, so a guard sitting in the scripts directory is inert. Declare it in this skill's `hooks.json` and boot wires it into `~/.claude/settings.json` for you:

```json
{
  "PreToolUse": [
    { "matcher": "Write|Edit", "script": "scripts/tmp_ref_guard.py" },
    { "matcher": "Bash", "script": "scripts/blind_mutation_guard.py" }
  ]
}
```

The path is relative to the skill, because a skill cannot know where it is installed and a hardcoded one is how a hook becomes a no-op on someone else's box. A declared script that is not on disk is skipped with a warning rather than wired to nothing.

This replaces a paragraph that asked you to hand-edit `settings.json`. Startup creates that file only when it is ABSENT and never rewrites an existing one, so on every box that already had one, a guard shipped by an upgrade stayed inert while the skill read as installed. The merge is add-only and keyed by command: your own entries are never touched, and re-running it changes nothing.

The matcher takes a tool name, a `|` alternation, or an MCP tool id (`mcp__vesta__mark_dreamer_complete`), so a guard can gate an agent-only action as well as a shell command.

A guard answers on stdout with `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}` and exits 0. Allow is silence. The reason string is the entire teaching moment, so it names the shape, why the failure is invisible, and the correct forms.

**Fail open, always.** An unreadable payload, an unexpected shape, or any exception allows the call. A guard that can wedge ordinary work gets routed around, and a routed-around guard gets deleted.

### Verifying

Failing open means a broken guard is indistinguishable from a healthy one from the outside: nothing is blocked, nothing is said. `verify_hooks.py` is what tells them apart. It walks the settings structure (not a grep for `.py`, which misses `bash -lc` wrappers and unexpanded `~` paths), and asks of every wired hook: is it there and does it parse, does it allow a benign call, and does it still DENY an input it must refuse. Only the third question catches a guard gutted to `sys.exit(0)`.

**When you add a guard, register its known-bad input in `must_deny()`** in the same pass. Without one, the guard can only be shown to parse and to allow, which is the state a gutted guard is in, and `verify_hooks.py` reports it by name as not fully exercised rather than counting it as a pass. Use the real call the guard was written for. For a guard whose verdict depends on state (a rolling budget, a file it reads), no fixed input can be known-bad: register cases in `STATEFUL` with a fixture that builds the state, and give BOTH directions, one it must refuse and one it must wave through. Deny-only cannot tell a working guard from one stuck on deny; allow-only cannot tell teeth from no teeth.

## Personality

Drift the active preset under `~/agent/skills/personality/presets/` directly (the active one is named by `agent_personality` in `~/agent/data/config.json`, or by `default_personality` in `~/agent/core/manifest.json` when the store has no entry; never by an env var), or the shared voice section in `~/agent/skills/personality/SKILL.md` for something true across all presets. Edit in place, surgical tweaks only, not rewrites. Swaps between presets are the user's call. You may edit anything, MEMORY.md and the Charter included, but the Charter is the slowly-changing invariant spine: touch it rarely and surgically, not on one bad afternoon.

**Mirror their style.** Watch how they actually text: slang, emoji, laugh shape ("lol" / "ahahah" / "LMAOOO" / "😂"), length, caps, punctuation, opens and closes. Adjust the Voice / Rules / How it sounds sections of the active preset file so it bends toward them. If they laugh with "haha" and your preset laughs with "💀", close the gap. If they never use emoji and the preset does, pull back. Accommodation, not mimicry, gradual not abrupt.

## User State (in MEMORY.md)

Update the "User State" section, your working model of where they're at. Write what tomorrow's you needs to know to not start from zero.

**Every dream produces one person-fact: a value, a fear, a love, a person who matters and why, not an operational tell. If today taught you nothing about who they are, write that down and be more curious tomorrow.**

**Check the category before the evidence.** The line above already excludes an operational tell, and that is the gate that gets skipped: an evidence gate applied to the wrong category only buys you a wrong claim that is better evidenced.

**Get the denominator before you write it.** The nightly quota is pressure, and at 4am a manufactured fact feels exactly like a noticed one. So when a person-fact generalizes from things you observed: count those instances, count how often the opposite happened in the same window, and ask whether you found it by going looking for it, since a search confirms whatever it was pointed at. More counter-instances than instances means a one-off, not a pattern. A wrong person-fact is worse than none, because it loads into every message tomorrow and shapes how you read them.

**"Before I asked" is not "unprompted".** You see one channel; the user has a life in several, and other people and other agents prompt them where you cannot see. Any fact of the form "they did it without being pushed" is a claim about the whole world made from one window, so record it as "no prompt from me" unless you actually know.

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

**When the file is near the cap, run `~/agent/skills/dream/scripts/memory-budget` instead of eyeballing it.** The size alone tells you the file is too big, never which part got bigger, so curation degenerates into rereading the whole thing looking for fat. This prints the growth since the last commit that touched MEMORY.md, **the lines added in that window longest first** (those are the trim candidates, and git already knows which they are), and a per-section breakdown so the cutting goes where the mass is. It exits non-zero above a soft budget (default 92% of the cap), so it can gate the work rather than just inform it: `memory-budget && <add the line>`. If a fix for "the file is too full" keeps resurfacing every night, the trim was never the missing piece.

**Review what curation removed.** After curating, diff MEMORY.md against the last dream checkpoint: `git log -n1 --format=%H --grep '^dream'`, then `git diff <sha> -- agent/MEMORY.md`. Match `^dream`, never the full `^dream: nightly checkpoint`: that exact phrase is a convention nothing enforces, so a checkpoint worded any other way is skipped, the baseline silently slides back a night, and the review compares against the wrong tree while every output still looks right. Commit tonight's checkpoint with the conventional wording anyway, so the loose match stays the safety net rather than the plan. **Sanity-check the date the lookup returns before trusting the diff**: a stale baseline inflates the removal list with rolling fields that were legitimately rewritten in between, so if the checkpoint it finds is older than the previous night, run `git log --oneline --since=<that date>` and look for a differently-named commit before concluding that night never committed. Every removed line needs an answer: graduated into a skill file (say where in tonight's summary), expired, or wrongly dropped, so restore it. `### User State` and the Self `**State**:` line are rewritten nightly by design; skip them. No prior checkpoint, no review. Old versions stay recoverable via `git show <sha>:agent/MEMORY.md`.

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

### Writing dated blocks into your own files: `scripts/note-top`

Anything paged out of MEMORY.md lands in a file you will re-read later under time pressure, so the
block that answers the question has to be the one you hit first, and its timestamp has to be true.
Both fail in the same way, and not from forgetting: **the natural motion is `cat >> file`, and the
natural motion appends**, so the newest block sinks to the bottom while a stale one keeps greeting
every future reader. Use `~/agent/skills/dream/scripts/note-top <file>` (block on stdin) instead. It inserts under the title,
respects a pinned `## CURRENT ANSWER` block by inserting below it, and `--append` covers a file that
is genuinely chronological.

It also fills in a literal `@@NOW@@` in your block from the clock, which matters more than tidiness:
the timestamp is what decides which of two contradicting blocks wins, so a block dated forward beats
a later, truer one, and re-reading never catches it because 14:40 looks exactly as reasonable as
14:39. Hand-typing the digits is the bypass, so the script warns when the first line carries a clock
time in the future rather than silently accepting it. A backticked `` `@@NOW@@` `` is being talked
about, not used, and is left alone.

Exit codes: 0 inserted, 1 usage or missing target, 2 empty input (nothing written).

## Workspace Cleanup

Keep the container's filesystem organized and disk usage under control.

- Delete temp files, stale downloads, leftover build artifacts
- **Sweep the harness's own scratch, which no one else will.** `~/.claude/projects/*/tool-results/`
  accumulates every image and PDF any WebFetch ever pulled, silently and forever: on one box it
  reached 109MB across 209 files spanning three weeks. Delete what is older than a week
  (`find ~/.claude/projects -path '*tool-results*' -type f -mtime +7 -delete`). **The `.jsonl` files
  in that same tree are NOT scratch**, compaction recovery points at them, so never sweep those.
  If the box uses the harness task tool, `~/.claude/tasks/` grows the same way and is worse, because
  the harness re-injects that list into context every turn, so it quietly colours what you surface.
  Read it, fold anything genuinely open into memory, then clear it.
- Check `df -h`, then size the places that actually grow. **`du -sh ~/` alone is not enough, because it cannot see `/tmp`**, and `/tmp` is where subagents put their heavy artifacts, so a large share of your footprint is invisible to it. Use `du -sh /root /tmp`, then `du -sh /tmp/* | sort -rh | head` to see what is actually there
- **Subagents leave big things behind and nothing reaps them.** A research pass that installs a package or runs a model leaves whole virtualenvs, hundreds of MB each, and a browsing pass leaves downloaded PDFs, page images and OCR output. The findings are already in your notes by then, so the artifacts are pure residue. Sweep `/tmp` for virtualenvs, `*.pdf`, `*.png` and scratch dirs after any pass that ran code or read sources, checking first that nothing is still running (no live background agents, `ps -eo comm | grep -c camoufox`). **A git worktree is not a scratch dir: remove it with `git -C ~ worktree remove <path>`, never `rm -rf`.** `/tmp/vesta-pr` is the worktree the Upstream phase creates earlier the same night, it holds no process so the "still running" check passes it, and deleting the directory leaves it registered, so the next `git worktree add` on that path fails with `missing but already registered`. `git -C ~ worktree list` names the ones to spare, and `git -C ~ worktree prune` is the recovery if one was already deleted that way
- **Before deleting anything large, check what it actually is, and beware two specific traps.**
  `du -sh <dir>/*` silently misses hidden entries, so a directory holding only a `.venv` reports
  nothing and reads as empty. And a multi-gigabyte CUDA or model cache may be load-bearing: confirm
  against `/dev/nvidia*` and the active skill list before assuming it is dead weight. Both nearly
  cost a working 7.6GB install on 9 Aug 2026.
- Stop daemons nothing needs any more (`<skill> daemon stop`), e.g. a file-host or sign-service you brought up for one errand
- Remove unused packages or build caches if they're taking significant space (`uv cache clean`, `apt clean`)

## Sensitive Data Cleanup

Run `~/agent/skills/dream/scripts/redact_secrets.sh` to scan the event DB and every channel store on the box (app-chat, whatsapp and telegram message stores including named instances, tasks, and the email send queues) for API keys, tokens, passwords, private keys, connection strings, and payment-card numbers (a digit run is reported only when it opens with a real card-issuer prefix and passes the Luhn check, so order numbers, tracking numbers, and timestamp ids stay out of the report). What the user actually typed lives in the channel stores, not in events.db, so those are where a pasted credential sits. The output opens with a coverage block, one line per store: read it before trusting a clean result, because a store marked `absent`, `TRUNCATED`, or `FAILED` was not (fully) checked and "no secrets found" covers only what was scanned. Each hit prints as `ref|context` with the value itself masked as `[REDACTED]`, so reviewing candidates never re-leaks a live secret into a new event; a ref is a bare event id for the events store (`412`) or `store:table:rowid` for a channel store (`whatsapp:messages:88`). Judge each from its context, then redact the real leaks in place with `redact_secrets.sh --scrub <ref> <ref> ...`: it replaces the secret with `[REDACTED]` in those rows while keeping their context and each store's search index intact, folds the store's write-ahead log into the main file and vacuums it so the scrubbed bytes do not linger in the `-wal` sidecar or in freed pages, then verifies the committed rows and the file's bytes and warns (exit 2) if a matched secret survived; on that exit code the secret is still on disk, act on the warning the same night. When a snippet is too short to judge, `redact_secrets.sh --show <ref>` prints that row's scannable text with every detected secret masked (identity columns, sender and chat ids, are not scanned and not shown). Read a stored row's raw data no other way: a raw row printed into your context re-leaks the live value into a new event. The scan runs every dream, so a value that re-seeds itself through later reasoning is simply caught and scrubbed again. Never quote a leaked value in your summary or anywhere else; refer to it indirectly. Also grep MEMORY.md and dreamer summaries for credentials and remove any you find. Secrets belong in env vars, not in history or files.

**Then scan the filesystem: `~/agent/skills/dream/scripts/scan_files_for_secrets.sh`.** `redact_secrets.sh` reads the event DB and the channel stores, which is where a credential the user pasted lands, and it cannot see files at all. Agents write credentials to files too (a token redirected into a file instead of a shell variable, a key material sidecar a tool left behind, a stray `.env`), so a store-only sweep reports clean on a whole class of leak it never looked at. This one walks `/tmp` and `$HOME` for credential-shaped names and high-confidence content signatures, prints each candidate's path and size and never its value, and never deletes: your own working key material and a leak look identical to a regex, so judge each hit and remove the real ones yourself. It exits 1 when there are candidates and 2 when a root it was given does not exist, so read the exit code and treat a `SKIP` line as coverage you did not get.

**Then run `~/agent/skills/dream/scripts/check_mail_residue.sh [domain ...]`, and read its scope lines.** The secrets scanner looks for credential SHAPES in the stores; this looks for mailbox CONTENT in files the agent itself wrote, which is a different surface. Pass the domain of any account the user has asked you to disconnect. It exists because of a real incident: an agent told to disconnect from a work mailbox removed the auth cache, the browser profiles and the notification rules, confirmed the account was gone from the mail skill's account list, and reported the mail "all removed and verified gone". Every one of those checks was clean and every one was the wrong surface. Thousands of messages sat in JSON the agent had written by hand during the session, and were found by accident three days later. The generalisable point is not the missed directory: a skill's store has a name the agent remembers, while a scratch file written in a hurry belongs to no subsystem and so is invisible to every check the agent would think to run. This one enumerates by content instead. Treat a clean run as "these roots were clean", never as "there is none", and leave what it reports under the inherent heading (logs, transcripts, the event database) exactly where it is: deleting the agent's own record to make a check go green is destroying evidence to protect a claim. That is also why "gone" is rarely an achievable promise once an agent has read something. The honest form is **disconnected, no residual access, working copies removed**.

**Scrubbing removes the copy, not the exposure.** A credential that is still valid stays live after every local copy is gone: the scrub narrows the surface, it does not close the leak. When a hit is a live credential the user pasted, tell them it ended up stored and suggest rotating it; do not report the matter closed because the scrub came back clean.

**The moment a hit is confirmed live** (the value is still in use), scrub it by literal rather than by ref, even when `--scrub <ref>` would clear every ref you saw. `--scrub <ref>` touches only the refs you pass it, so an identical value sitting in a store or row you never got a ref for survives the scrub and still reports clean. `redact_secrets.sh --scrub-literal '<value>'` is value-keyed and store-wide, so it sweeps every store in one shot: run it for any confirmed-live secret, and do not report the value clean until it prints `0` remaining across every store.

**For a value the scanner cannot detect but you know exactly** (a human-chosen password matches no API-key shape, and `--scrub` on its rows prints `0 rows changed` while the value stays put): `redact_secrets.sh --scrub-literal '<exact value>'` replaces every stored copy across every store on the box, prints only per-store counts and the value's length (never the value), keeps each search index in sync, and refuses values under 6 characters because the rewrite is store-wide. The same command is the fix when `--scrub` exits 2 with a warning that a matched secret survived. `--scrub-literal` verifies the committed rows too, and exits 2 when a copy sits where a JSON rewrite cannot reach it (a bare JSON number): fix those rows by hand. After a literal scrub, re-run it once at the end of the night: the command that invoked it may itself be recorded as a new event.

## Summary

Write what you did and why to `~/agent/dreamer/YYYY-MM-DDTHHMM.md` (e.g. `2026-04-14T0347.md`). The minutes matter: two dreams in the same hour must not overwrite each other.

The user reviews this summary, so it's an accountability record, not a private log.

Cover the whole night, not just the fixes: record an outcome for **every** phase, in the order of operations, a no-op is a valid outcome worth stating ("nothing to prune", "no upstreamable finds") so tomorrow's you knows the phase actually ran and found nothing. Close with what's still unresolved and what tomorrow should pick up.

**Set a reminder for future-you.** If tonight surfaced something for future-you to do at a moment (ask them a question, follow up on an event, re-check a blocker), set it as a reminder with the `tasks` skill on your own channel.

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

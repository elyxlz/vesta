---
name: writing
description: Draft, rewrite, or polish prose for the user: chat and email replies, important emails, posts, articles, cover letters, coursework essays, dissertation chapters, journal and conference papers. Use whenever the user asks for text another human will read, whatever the length.
---

# Writing

You broker every writing job; you never draft the prose yourself. Your context holds notifications, tool output, and your own assistant register, and all of it leaks into prose written directly. The writer is a sub-agent whose entire world is a brief you compose, so the text carries the user's voice and only the facts you chose to hand over.

## Roles

- **You (broker)**: pick the tier, gather what the brief needs, mine voice exemplars, spawn the writer and reviewers, aggregate feedback, deliver to the user.
- **Writer**: a fresh sub-agent per draft. Its prompt is the full text of `writer_prompt.md`, then the brief, then (on revision rounds) the current draft and the aggregated review notes. Give it nothing else; if the writer needs a fact, the fix is putting the fact in the brief.
- **Reviewers**: sub-agents spawned in parallel at the standard and academic tiers, one per prompt file, each given the draft plus the inputs its file names.

## Tiers

Three fixed tiers. Pick by stakes, not length; state which tier you picked and switch if the user pushes back.

| Tier | Typical jobs | Rounds | Reviewers |
| --- | --- | --- | --- |
| quick | chat replies, short emails, captions | 1 | none |
| standard | important emails, articles, posts, cover letters, announcements | up to 2 | humanizer, voice |
| academic | coursework essays, dissertation chapters, journal and conference papers | up to 5 | rubric, voice, citation, AI detection, plus coherence and plagiarism before delivery |

### Quick

No approach session, no files. Compose the brief inline in the writer's prompt: recipient, goal, the thread or message being answered, hard facts, and a few voice exemplars when a channel skill can fetch them cheaply. Spawn one writer. Check the result states only facts from the brief and reads like the user, resolve any `MISSING:` lines by respawning with the fact added, and deliver.

### Standard

Hold a short approach exchange first: audience, goal, length, tone, anything the user wants said or avoided. Create the job directory (see State) and write `brief.md`. Then loop, at most two rounds:

1. Spawn a fresh writer. Save its output as the round's draft.
2. Spawn both reviewers in parallel: `humanizer_review.md` (draft plus exemplars) and `voice_review.md` (the draft hidden among the exemplars).
3. Pass is `cluster_verdict: pass` and the voice reviewer failing to pick the draft (`guess_confidence` below 0.5 or a wrong guess). On pass, deliver. Otherwise aggregate the notes, weakest axis first, and go to 1.

Deliver with any residual findings flagged honestly.

### Academic

The heavyweight tier, in two phases.

**Phase 1, approach session.** Lock down with the user before any drafting:

1. **Task**: what is being written, audience, deadline, length.
2. **Plan + thesis**: structure, section word allocations, the core claim, the analytical lens.
3. **In-distribution corpus**: the reference texts the voice reviewer uses. Course exemplars, 3 to 5 recent papers from the target journal, last year's best conference papers, or user-supplied texts. If no real exemplar exists but the marker has published their own writing on the topic, use that as a quasi-exemplar: the voice differs but the framing, citation tier, and rhetorical moves are signals the marker is calibrated to. **With no real corpus and no quasi-exemplar, drop the voice reviewer.** Never pivot to synthetic essays: a reviewer judging against generated references says nothing about a real human marker.
4. **Background reading corpus**: what the writing must engage with, distinct from the in-distribution corpus. Course slides, reading lists, the marker's published positions, or the 5 to 10 most-cited recent papers. Read enough before drafting that the brief can carry specific engagement: canonical readings cited, contested positions taken. Pass this corpus to the rubric and citation reviewers too.
5. **Rubric**: the markscheme, journal review criteria, or a rubric you scaffold from the writing type and field.
6. **Citation conventions**: the style (Harvard, Chicago, APA, MLA, Vancouver, IEEE, journal-specific) and what must be primary literature.
7. **AI-detection threshold**: default 15 percent overall AI-likelihood; push to 5 when the institution penalises AI use, deprioritise when the marker is openly permissive.

Surface the locked plan and wait for the user's OK before drafting.

**Phase 2, the loop.** Write the brief (plan, thesis, corpus digests, rubric, citation rules all go in it). Then, for round 1, 2, ... up to 5:

1. Spawn a fresh writer. Save the draft.
2. Spawn reviewers in parallel: `rubric_prompt.md` (rubric + draft + brief), `voice_review.md` (draft hidden in the anonymised corpus), `citation_prompt.md` (draft + style + corpus), and `gptzero.py` on the draft file (a script, not a sub-agent).
3. All thresholds met: run `coherence_prompt.md` and `plagiarism_prompt.md` once as the final gate, fix what they find, and present. 5 rounds without convergence: present the current state honestly.
4. Otherwise aggregate, weakest axis first, and go to 1.

Thresholds: every rubric criterion at the target tier (default the 70 percent band); voice reviewer `guess_confidence` below 0.5 or guess wrong; zero hallucinated citations and 100 percent style consistency; AI-likelihood under the locked threshold.

**Anonymisation for the voice review.** Strip from the draft and every corpus text: names, candidate numbers, any tic that marks a text as the user's, and **all citation dates**, replacing `(Smith, 2024)` with `(Smith, YEAR)` in text and reference list both, so recency cannot be the tell. Strip URLs and DOIs that reveal years. Export PDFs to plain text to drop metadata.

## The brief

`brief.md` is the writer's entire world. Its sections, in order: Task, Audience, Goal, Length and format, Hard facts, Voice exemplars, Background material, Tone notes. Hard facts holds every name, date, number, link, and quote the piece may state; the writer is forbidden to state anything absent from the brief and returns `MISSING:` lines when a needed fact is not there. Answer a `MISSING:` line by adding the fact and respawning, never by letting a guess stand.

## Voice exemplars

The default voice is the user's own. Mine exemplars from the genre being written: sent emails via the email skills, chats via the whatsapp or telegram skills, posts or essays the user supplies. Three to five short verbatim samples beat one long one. With no exemplar available, say so in the brief and have the writer go neutral and plain. Academic corpora follow the academic tier's anonymisation rules.

## State

- Quick: no files.
- Standard and academic: one directory per job, `~/agent/data/writing/<YYYY-MM-DD>-<slug>/` (for example `2026-08-15-cover-letter-acme/`), holding `brief.md`, `draft.md` (current), `iterations/round_<N>/` (draft snapshot, each review's output, and a `summary.md` of what changed and why), and `scores.json` (running tally, latest round first). Resumable after a crash: reread the brief and the latest round, continue the loop.
- A job tied to a tracked task also gets its directory path noted in that task's metadata file. The store never depends on a task existing.

## Tools

- `python3 ~/agent/skills/writing/gptzero.py <file.md>`: AI-likelihood JSON, per sentence and overall. Academic tier.
- `python3 ~/agent/skills/writing/papers.py search|get|refs|cited-by|similar|pdf`: OpenAlex search and PDF fetch for corpora and citation checks. Academic tier.
- `python3 ~/agent/skills/writing/dictionary.py syn|alt|ban-replace`: word-level swaps that leave sentence structure alone. Any tier.

## Notes

- Never pad a draft to satisfy a metric, and never flatten the user's voice into something generic; the reviewers pull toward idiosyncratic, human prose, so lean into it.
- The citation reviewer does web lookups and can be slow; spawn it with the others and accept the longer round.
- Present residual gaps honestly. A sound piece with a flagged weakness beats a polished one with a hallucinated citation.

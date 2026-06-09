---
name: issue-triage
description: >
  Use when the user asks to triage, tag, label, categorize, rename, or de-duplicate GitHub issues
  and PRs in the Vesta repo ("triage open issues", "tag all issues", "label this issue",
  "add labels", "standardize issue titles", "rename PR titles", "normalize titles", "find
  duplicate issues", "merge duplicates"). Applies the standardized Vesta label taxonomy
  (type + priority + area), the conventional-commits title format, and a duplicate-merging policy
  so labeling, naming, and the open-issue set stay consistent across sessions.
---

# Vesta Issue & PR Triage

Three jobs:

1. **Labels** — every triaged issue gets exactly **one type label**, exactly **one priority
   label**, and **one or more area labels**.
2. **Title** — every issue and PR title follows the conventional-commits format
   `type(scope): description`, lowercase, imperative, no trailing period.
3. **Duplicates** — for every cluster of issues that report the same broken behavior or feature
   ask, keep one canonical and close the rest as duplicates, preserving any non-overlapping
   information into the canonical.

If the user asks to "tag" or "triage", do all three. If they ask only to "label", do labels only.
If they ask only to "rename" / "standardize titles", do titles only. If they ask only to
"de-dup" / "find duplicates" / "merge duplicates", do duplicates only.

## Workflow

1. List candidates:
   ```
   gh issue list --limit 100 --state open --json number,title,labels
   gh pr list   --limit 100 --state open --json number,title       # only when normalizing PR titles too
   ```
2. For each item, read the title. If the title alone is ambiguous, `gh issue view <N>` (or
   `gh pr view <N>`) to read the body before deciding labels, renaming, or judging duplicates.
3. **Duplicate pass first** (if in scope) — see "Duplicate Detection & Merging" below. Resolve
   duplicates before labeling/renaming so you don't waste edits on issues you're about to close.
4. Decide labels from the taxonomy below. Apply with `gh issue edit <N> --add-label "a,b,c"`.
5. Decide the canonical title from the rules below. If the current title already matches, leave it
   alone. Otherwise rename with `gh issue edit <N> --title "..."` or `gh pr edit <N> --title "..."`.
6. Items that already have a complete label set (type + priority + area) **and** a conformant title
   should be left alone unless the user asked for a re-triage.

Run the `gh issue edit` / `gh pr edit` calls in parallel when processing many items at once.

## Duplicate Detection & Merging

**Goal:** for every set of open issues that describe the same underlying broken behavior or
feature ask, keep one canonical and close the rest as duplicates without losing information.

### How to find candidates

1. Read titles + bodies for all open issues. Group by area label first — duplicates almost never
   cross areas.
2. Within each area, look for clusters that share at least two of:
   - Same observed symptom (e.g. "TTS audio buffered then dumped on mic release").
   - Same proposed remediation (e.g. "stream chunks immediately instead of buffering").
   - Same triggering scenario (e.g. "after upgrading to v0.1.148 on Android").
3. Sub-issues that are fully covered by a parent's acceptance criteria count as duplicates of the
   parent.
4. PRs are not deduped — only issues. A PR that fixes an open issue is not a duplicate; that's a
   normal "Fixes #N" relationship.

### Pick the canonical

Within a cluster, the canonical is the issue you keep open. Prefer (in order):

1. The issue with the most concrete acceptance criteria or repro.
2. The issue with the lowest number (older, usually more cross-referenced).
3. If both are equally well-written, keep the lower number.

### Decide what to merge

Diff the duplicate's body against the canonical's body. Identify content in the duplicate that is
**not** present in the canonical:

- Distinct repro steps or environments (e.g. "also reproduces on Android 14, not just iOS").
- Additional log snippets, stack traces, or error messages.
- Acceptance criteria the canonical didn't cover.
- Linked PRs, related issues, or external references.
- Reactions/upvote counts are signal but not content; don't merge them.

If the duplicate is a strict subset of the canonical (no new info), skip the merge step and just
close.

### Apply the merge

For each duplicate `D` of canonical `C`:

1. **Preserve unique info** (only if `D` has any). Post a comment on `C`:
   ```
   gh issue comment <C> --body "Merged from #<D>:

   <quoted unique content from D's body, as a markdown blockquote>"
   ```
2. **Cross-reference + close `D`.** Use `not planned` as the reason (gh CLI doesn't expose a
   `duplicate` reason; the cross-reference + label do the rest):
   ```
   gh issue close <D> --reason "not planned" --comment "Duplicate of #<C>. Unique details merged into the canonical issue."
   gh issue edit  <D> --add-label "duplicate"
   ```
3. **Do not** rename or add taxonomy labels to `D` — it's about to be closed.

Run the comment + close + label calls for one duplicate sequentially (the close depends on the
comment landing). Across multiple unrelated clusters, run them in parallel.

### Surface ambiguous candidates instead of closing

Closing issues is visible to others and reverses poorly. Auto-merge only when the cluster is
unambiguous (≥2 of the cluster signals above plus matching area). For borderline pairs, list them
in your end-of-run report and ask the user to confirm before closing — don't guess.

Borderline indicators that should bump you to "ask the user":

- Same area but different observed symptoms ("UI flashes" vs "UI freezes").
- Same component but different root-cause hypotheses.
- One is a P0/P1 incident report and the other is a long-form design proposal — they may both be
  legitimate (the incident gets fixed; the proposal is the longer-term redesign).
- Either issue has multiple participants in the comments — closing erases context for them.

### Don'ts (duplicates)

- Don't close as duplicate without leaving a comment that names the canonical issue.
- Don't merge information that is identical or near-identical — only the genuinely unique parts.
- Don't paraphrase the duplicate's content when merging; quote it verbatim so the author's wording
  is preserved.
- Don't merge across `bug` ↔ `enhancement` boundaries even if the topic is similar — those are
  separate problems by definition.
- Don't dedupe PRs.
- Don't reopen previously-closed duplicates to "re-merge" them. If the canonical was closed, leave
  the duplicate alone and surface it.

## Title Standardization

### Format

```
type(scope): short imperative description
```

- **type** — required. One of: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `ci`, `chore`,
  `style`, `build`. Map from the issue/PR's intent (see "Type → label mapping" below).
- **scope** — required when a clear single area applies; omit `()` when the change spans many
  areas (rare). Use the lowercase area name or a finer-grained sub-system: `agent`, `app`,
  `vestad`, `cli`, `skills`, `dream`, `tasks`, `whatsapp`, `voice`, `finance`, `agentmail`,
  `integration`, `tls`, `security`, `infra`, or a specific skill name (`onedrive`, `media-server`,
  `home-assistant`, `agentmail`, etc.) when the work lives inside that skill.
- **description** — imperative present tense ("add", "fix", "remove" — not "added" / "adds" /
  "fixed"), lowercase first word (proper nouns/acronyms keep their case), no trailing period,
  ≤72 chars when feasible. Don't repeat the type or scope in the description.

### Type → label mapping

| Title type | Implies label |
| --- | --- |
| `feat` | `enhancement` |
| `fix` | `bug` |
| `docs` | `documentation` |
| `refactor`, `perf`, `test`, `ci`, `chore`, `style`, `build` | no required type label; pick from taxonomy if the work also fits one |

If the title type and the chosen label disagree (e.g. title `feat(...)` but you labeled it `bug`),
one of them is wrong. Re-read the body and reconcile before saving.

### Issue vs PR titles

PRs almost always describe a single change → use the strict `type(scope): description` form.
Issues sometimes describe a problem without a fix in mind. Still prefer `type(scope): description`,
where the type reflects the *intended outcome*:

- A reported breakage → `fix(scope): <what is broken>`
- A feature request → `feat(scope): <what to add>`
- A docs gap → `docs(scope): <what to document>`
- An open investigation with no committed direction → drop the type and use `scope: <question>`
  (and add the `research` or `question` label).

### Normalization examples

| Before | After |
| --- | --- |
| `app: chat UI becomes very slow once tool calls are rendered` | `fix(app): chat UI slows once tool calls are rendered` |
| `app: v0.1.148 Android TTS audio buffered, dumped on mic release instead of streaming live (regression from 0.1.147, likely PR #416)` | `fix(voice): android TTS buffers audio instead of streaming (v0.1.148 regression)` |
| `Add VPN and media-server skills` | `feat(skills): add VPN and media-server skills` |
| `whatsapp: spurious delivery_failure notifications and misleading filtered status` | `fix(whatsapp): stop firing spurious delivery_failure notifications` |
| `OneDrive setup: pin rclone to v1.73+ to fix personal-OneDrive content fetches` | `fix(onedrive): pin rclone to v1.73+ to fix personal-account fetches` |
| `bug: nightly dreamer crash mid-execution leaves MEMORY.md wiped with no recovery` | `fix(dream): preserve MEMORY.md when nightly dreamer crashes mid-run` |
| `vestad: \`perform_update\` should be a no-op when already at the latest version` | `fix(vestad): make perform_update a no-op when already at latest` |
| `skill: cloudflare-email for agent send/receive via Cloudflare Email Service` | `feat(skills): add cloudflare-email skill` |

### Don'ts (titles)

- Don't include issue/PR numbers, version tags (`v0.1.148`), or commit hashes in the title unless
  load-bearing for the bug report; prefer to put that detail in the body.
- Don't include trailing parentheticals describing the cause ("(regression from PR #416)") unless
  the cause is the headline.
- Don't capitalize the description after the colon.
- Don't add a period at the end.
- Don't double-tag (`fix(bug): ...`, `feat(enhancement): ...`) — the type already conveys this.
- Don't change the title of a merged PR; only rename open PRs and issues.

## Taxonomy (labels)

### Type — pick exactly one

| Label | When to apply |
| --- | --- |
| `bug` | Something is broken, regressed, crashes, hangs, produces wrong output, or violates a documented invariant. Title cues: "fix", "broken", "regression", "race condition", "hangs", "blocks", "flashes". |
| `enhancement` | New feature, new capability, or a meaningful UX/quality improvement on existing behavior. Title cues: "feat:", "feat(...)", "add", "support", "make ... first-class". |
| `documentation` | Docs, README, CLAUDE.md, SKILL.md, or comments only. No behavior change. |
| `question` | Open question or request for information, no concrete deliverable yet. |
| `research` | Investigation / spike where the outcome is a decision or a writeup, not a shipped change. Title cues: "investigate", "explore", "evaluate". |

A single issue should not get both `bug` and `enhancement`. If a regression is reported alongside a feature ask, prefer `bug` and note the feature in a follow-up.

### Priority — pick exactly one

| Label | When to apply |
| --- | --- |
| `P0-critical` | Blocks normal operation right now: data loss risk, can't start the agent, broken backup, security incident, prod outage. Use sparingly. |
| `P1-important` | Significant impact but not a stop-the-world: major UX regressions, perf cliffs that make a flow unusable, auth/notification reliability bugs. |
| `P2-normal` | Default for most feature requests and non-blocking bugs. When unsure between P1 and P2, choose P2. |
| `P3-low` | Nice to have, polish, niche tooling, low-traffic CI/infra ergonomics. |

### Area — pick one or more

Apply every area that the issue genuinely touches. Most issues need 1–2 area labels.

| Label | Scope |
| --- | --- |
| `agent` | Python agent core: `agent/core/` loops, message processing, notifications, memory, dreamer, EventBus. |
| `app` | Desktop or mobile Tauri app, including `apps/web/`, `apps/desktop/`, `apps/mobile/`. UI bugs, app-side connection logic, auth UX. |
| `voice` | TTS / STT / voice pipeline (any platform). |
| `whatsapp` | WhatsApp integration / CLI / skill. |
| `cli` | `vesta` CLI client (`cli/` Rust crate). |
| `vestad` | `vestad` daemon (`vestad/` Rust crate): Docker management, HTTP/WS gateway, agent lifecycle. |
| `skills` | Anything under `agent/skills/` or `agent/core/skills/` (skill content, scripts, index). |
| `infra` | Docker, CI, GitHub Actions, release pipeline, hosting, signing certs. |
| `security` | Auth, tokens, credential handling, access control, supply chain. |
| `tls` | TLS / cert pinning / self-signed cert handling specifically. Pair with `security` when about trust. |

Note: `app` and `vestad` can co-occur (e.g. "view gateway logs from inside the app"). Apply both when the issue spans the boundary.

## Heuristics & Examples

- **"feat(app): X"** → `enhancement` + `app` + priority based on user impact (default `P2-normal`).
- **"app: <thing> is slow / flashes / blocks"** → `bug` + `app` + priority by severity. Hard freezes or unusable flows = `P1-important`; cosmetic flicker = `P3-low`.
- **"backup ... urgently"** or anything risking data loss → `bug` + `vestad` + `infra` + `P0-critical`.
- **TTS regressions on a specific app version** → `bug` + `app` + `voice` + `P1-important` (audio regressions are high-impact).
- **Auth / credential / cert issues** → add `security`. If specifically about TLS trust, also add `tls`.
- **"feat(skills): ..."** → `enhancement` + `skills`. Add a second area if the skill is tied to one (e.g. `whatsapp`).
- **Compaction / loop / message-processing bugs** → `bug` + `agent`.

## Don'ts

- Don't invent labels. If something doesn't fit, surface it to the user and let them decide whether to add a new label to the repo (`gh label create ...`).
- Don't relabel issues that already have a complete (type + priority + area) set unless the user asked.
- Don't use `bug` for missing features. Missing != broken.
- Don't apply `P0-critical` to feature requests. P0 is reserved for things that are currently breaking the user.
- Don't add the dependency-update / language-tag labels (`dependencies`, `rust`, `python`, `javascript`, `github_actions`) by hand — those are for Dependabot PRs.
- Don't rewrite a title beyond format normalization. Preserve the author's intent and key technical
  details; if the body says something the title omits, leave the body alone.

## Verification

After labeling and renaming, re-run:
```
gh issue list --limit 100 --state open --json number,title,labels
gh pr list   --limit 100 --state open --json number,title         # if PRs were in scope
```
Confirm every open issue has at least one type label, one priority label, and one area label, and
that every title matches `type(scope): description` (or `scope: description` for open
investigations). Report any item you intentionally skipped and why.

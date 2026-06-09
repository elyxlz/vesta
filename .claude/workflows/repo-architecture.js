export const meta = {
  name: 'repo-architecture',
  description: 'Higher-altitude pass: audit the whole system against the codified Architecture Principles and the elegance north star; specifiable improvements become PRs (including structural simplifications), genuine design forks become GitHub issues',
  whenToUse: 'Recurring architecture and test-strategy review. Defaults to landing verified PRs; reserves issues for decisions that genuinely need the user.',
  phases: [
    { title: 'Audit', detail: 'per architectural concern, whole-system survey' },
    { title: 'Triage', detail: 'dedup, verify, group into PRs and issues' },
    { title: 'Implement', detail: 'worktree PRs + issues' },
  ],
}

// fable for architecture judgment and structural rewrites; sonnet for check-verified surgical work; haiku for gh chores.
const deep = (prompt, opts) => agent(prompt, { model: 'fable', ...opts })
const run = (prompt, opts) => agent(prompt, { model: 'sonnet', ...opts })
const fast = (prompt, opts) => agent(prompt, { model: 'haiku', ...opts })

const NORTH_STAR = `NORTH STAR: elegance. 90% of the value for 10% of the effort. The best architecture has fewer moving parts, not better-managed ones. Be bold in scope, ruthless in the result: merge modules, delete layers, collapse config into defaults; the system must END SIMPLER. Vesta is a single-tenant personal daemon: never propose distributed-systems ceremony (circuit breakers, bulkheads, dashboards). A complex final design is failure, not ambition.`

const SYSTEM_CONTEXT = `Intentional design, never propose unwinding:
- vestad daemon (Rust: Docker + HTTP/WS API), vesta CLI (Rust), Python agent in Docker, React SPA in Tauri. No shared crate between cli and vestad. No MCP servers.
- The agent drives the claude CLI in tmux via the in-repo cc_sdk, not the official SDK.
- SQLite events.db (FTS5), persisted session_id for resume, restic snapshot backups.
- Functional Python (no classes-with-methods, no getattr/.get fallback/hasattr); Rust without panic/unwrap/expect on fallible paths; no dashes in prose; check.sh is the single test entry point; release.sh owns versions (never bump in a PR).`

const RULES = `Rubric: read root CLAUDE.md (Architecture + Architecture Principles, including the conflicts already resolved in our favor) and CONTRIBUTING.md (Testing strategy, Karpathy Guidelines) first; they override external canon.`

const PR_RULES = `Branch from origin/master (git fetch origin master, git checkout -b <branch> origin/master). Never weaken or delete a test to pass. Commit ending with the Co-Authored-By trailer for Claude, push -u origin, gh pr create --base master. Body: what and why, no dashes, ending with the Generated with Claude Code trailer.`

const AREA_CHECK = {
  agent: './check.sh agent',
  cli: './check.sh cli',
  vestad: './check.sh vestad',
  web: './check.sh web',
  repo: './check.sh all',
}

const CONCERNS = [
  { key: 'elegance', focus: 'where the system could be radically simpler: modules that could merge, layers or indirection that could disappear, config that could become a default, duplicated mechanisms that could unify' },
  { key: 'boundaries', focus: 'module boundaries, coupling and cohesion, leaky abstractions, deep vs shallow modules, dependency direction across cli, vestad, agent, web' },
  { key: 'error-resilience', focus: 'error-handling consistency, failure modes, timeouts, retries, resource cleanup, cancellation, the message-interruption path' },
  { key: 'concurrency-state', focus: 'async task lifecycle, shared mutable state, races, backpressure, the message and notification loops, websocket lifecycle' },
  { key: 'testing', focus: 'test-pyramid balance, untested critical paths, flaky tests, assertion quality, missing integration coverage, hermeticity' },
  { key: 'data-integrity', focus: 'events.db schema and migrations, session persistence, backup and restore correctness, FTS usage' },
]

const AUDIT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
    title: { type: 'string' }, concern: { type: 'string' },
    evidence: { type: 'array', items: { type: 'string' } },
    severity: { type: 'string', enum: ['low', 'medium', 'high'] },
    remedy: { type: 'string', enum: ['pr', 'issue'] },
    effort: { type: 'string', enum: ['small', 'medium', 'large'] },
    rationale: { type: 'string' }, proposal: { type: 'string' },
  }, required: ['title', 'evidence', 'severity', 'remedy', 'effort', 'rationale', 'proposal'] } } },
  required: ['findings'],
}

const TRIAGE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    issues: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
      title: { type: 'string' }, body: { type: 'string' },
      priority: { type: 'string', enum: ['low', 'medium', 'high'] },
      effort: { type: 'string', enum: ['small', 'medium', 'large'] },
      labels: { type: 'array', items: { type: 'string' } },
    }, required: ['title', 'body', 'priority', 'effort'] } },
    prGroups: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
      area: { type: 'string', enum: ['agent', 'cli', 'vestad', 'web', 'repo'] },
      theme: { type: 'string' },
      ambition: { type: 'string', enum: ['surgical', 'structural'], description: 'structural = a behavior-preserving simplification that reshapes code' },
      tasks: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
        title: { type: 'string' }, file: { type: 'string' }, fix: { type: 'string' }, rationale: { type: 'string' },
      }, required: ['title', 'fix', 'rationale'] } },
    }, required: ['area', 'theme', 'ambition', 'tasks'] } },
    droppedCount: { type: 'number' },
  }, required: ['issues', 'prGroups'],
}

const PR_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    label: { type: 'string' }, branch: { type: ['string', 'null'] }, prUrl: { type: ['string', 'null'] },
    checksPassed: { type: 'boolean' }, changesSummary: { type: 'string' },
    filesChanged: { type: 'array', items: { type: 'string' } }, note: { type: 'string' },
  }, required: ['label', 'checksPassed', 'changesSummary', 'note'],
}

const ISSUES_RESULT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    created: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
      title: { type: 'string' }, url: { type: 'string' },
    }, required: ['title', 'url'] } },
    skipped: { type: 'array', items: { type: 'string' } },
    note: { type: 'string' },
  }, required: ['created', 'note'],
}

// ---- Audit ----
phase('Audit')
const auditByConcern = (await parallel(CONCERNS.map((concern) => () =>
  deep(
    `Audit the whole Vesta system for the '${concern.key}' concern: ${concern.focus}.
Architectural and test-level review, not line-by-line style. Build a mental model first: read CLAUDE.md and the relevant modules across agent/, vestad/, cli/, apps/web/.
${RULES}
${NORTH_STAR}
${SYSTEM_CONTEXT}
Each finding: title, concern, evidence (file paths + line ranges), severity, effort, crisp rationale, concrete proposal. Remedy:
- 'pr' (DEFAULT): anything specifiable and verifiable autonomously, including structural simplifications (merge modules, collapse abstractions, delete layers) provable by the check.sh suites. Do not shrink a real fix to make it PR-safe.
- 'issue': only genuine design forks (several viable directions the user must choose between, product calls, compat-risky migrations, needs a live agent to verify).
Do not edit anything.`,
    { phase: 'Audit', label: `audit:${concern.key}`, schema: AUDIT_SCHEMA },
  )))).filter(Boolean)

const allFindings = auditByConcern.flatMap((r) => r.findings)
log(`${allFindings.length} findings across ${CONCERNS.length} concerns`)

// ---- Triage (needs all findings together) ----
phase('Triage')
const triage = (await deep(
  `Triage these architecture findings.
${NORTH_STAR}
${SYSTEM_CONTEXT}
1. Dedup, then verify each by reading the cited code; discard the speculative, the wrong, and anything fighting the intentional design. Run \`gh pr list --state open\` first: drop tasks an open PR already covers; closed-unmerged PRs from prior runs are rejected taste, do not re-propose them.
2. prGroups (the default destination): coherent reviewable PRs by area (agent, cli, vestad, web, repo). Up to 5 groups, up to 5 tasks each, precise fix instructions. ambition='surgical' for contained fixes and tests; ambition='structural' for one behavior-preserving simplification per group with a reviewable diff.
3. issues: only genuine design forks needing the user's call. Up to 8, highest value first. Body sections: Problem, Evidence, Proposed direction, Alternatives considered, Effort and risk. No dashes. Suggest labels (type:architecture, type:tech-debt, area:*).
Findings: ${JSON.stringify(allFindings)}`,
  { phase: 'Triage', label: 'triage', schema: TRIAGE_SCHEMA },
)) || { issues: [], prGroups: [] }

log(`Triage: ${triage.prGroups.length} PR groups, ${triage.issues.length} issue proposals`)

// ---- Implement ----
phase('Implement')

const issuesThunk = () =>
  triage.issues.length > 0
    ? fast(
        `Create GitHub issues for these proposals (repo elyxlz/vesta, use gh).
First 'gh issue list --state open --limit 100': skip clear duplicates (record in skipped). Then 'gh label list': apply only labels that already exist (do not create or fail on labels). Create the rest with 'gh issue create --title ... --body ...' using each body verbatim. Return created[] and skipped[].
Proposals: ${JSON.stringify(triage.issues)}`,
        { phase: 'Implement', label: 'issues', schema: ISSUES_RESULT_SCHEMA },
      )
    : Promise.resolve({ created: [], skipped: [], note: 'no issue proposals' })

const prThunks = triage.prGroups.map((group, idx) => () =>
  (group.ambition === 'structural' ? deep : run)(
    `Land a ${group.ambition} PR for '${group.area}' in your worktree. Branch chore/arch-${group.area}-${idx}. Theme: ${group.theme}.
${NORTH_STAR}
${SYSTEM_CONTEXT}
${group.ambition === 'structural'
  ? `Re-architect as boldly as the tasks need, but behavior is preserved: existing tests pass unchanged (add one only at an untested seam). Before opening, re-read the full diff: if the result is not clearly simpler, ABORT with a note (a good outcome).`
  : `Tasks are surgical and self-contained (tests, CI gates, small reliability fixes); drop with a note any task that turns out to need structural change.`}
No unrelated refactors, no CLAUDE.md or lockfile edits. Run ${AREA_CHECK[group.area] || './check.sh all'} until green (for 'repo', also the affected area suites); drop tasks that cannot pass.
${PR_RULES} Title '${group.ambition === 'structural' ? 'refactor' : 'test'}(${group.area}): <short theme>' (ci/fix where apt)${group.ambition === 'structural' ? '; body quantifies lines removed vs added' : ''}.
Tasks: ${JSON.stringify(group.tasks)}
Return label='${group.area}-${idx}', prUrl, branch, checksPassed, filesChanged, changesSummary, note. No PR if nothing lands.`,
    { phase: 'Implement', label: `pr:${group.area}-${idx}`, isolation: 'worktree', schema: PR_SCHEMA },
  ))

const [issuesResult, prResults] = await Promise.all([issuesThunk(), parallel(prThunks)])

const prs = prResults.filter(Boolean)
const openedPrs = prs.filter((r) => r.prUrl)
log(`Done: ${openedPrs.length} PR(s), ${(issuesResult.created || []).length} issue(s)`)
return {
  prsOpened: openedPrs.map((r) => ({ label: r.label, url: r.prUrl, summary: r.changesSummary })),
  prsNoOp: prs.filter((r) => !r.prUrl).map((r) => ({ label: r.label, checksPassed: r.checksPassed, note: r.note })),
  issuesCreated: (issuesResult.created || []).map((i) => ({ title: i.title, url: i.url })),
  issuesSkipped: issuesResult.skipped || [],
}

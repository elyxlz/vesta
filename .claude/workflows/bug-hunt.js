export const meta = {
  name: 'bug-hunt',
  description: 'Hunt real bugs with diverse finder lenses; a bug survives only if a failing test proves it; fix PRs ship the regression test',
  whenToUse: 'Recurring correctness pass across agent, cli, vestad, web. Complements repo-quality (style/elegance) and repo-architecture (design) with proven-by-test bug fixing.',
  phases: [
    { title: 'Hunt', detail: 'parallel finder lenses, rounds until dry' },
    { title: 'Prove', detail: 'write a failing test or kill the claim' },
    { title: 'Curate', detail: 'dedup proven bugs, rank, cap' },
    { title: 'Fix', detail: 'one worktree PR per bug, regression test included' },
  ],
}

// fable to find subtle bugs (a missed bug is never recovered downstream); sonnet for proof and fixes (the failing test is the gate).
const deep = (prompt, opts) => agent(prompt, { model: 'fable', ...opts })
const run = (prompt, opts) => agent(prompt, { model: 'sonnet', ...opts })

const MAX_ROUNDS = 3
const MAX_FIXES = 6

const NORTH_STAR = `NORTH STAR: a proven bug, not a plausible one. Every claim must survive a failing test or die. Fixes are minimal and elegant: the smallest change that makes the test pass without weakening anything else.`

const TESTS_HOWTO = `Where tests live and the house rules:
- agent: agent/tests/ (pytest, run 'cd agent && uv run pytest tests/<file> -x'). Use the high-fidelity fakes (tests/fake_claude.py) and poll with tests/wait_util.py; NEVER sleep to await a condition. Hermetic: own tmpdir db/dirs, no running agent, no Docker.
- cli: cargo test in cli/. vestad: cargo test -p vestad in vestad/ (do not add Docker-gated tests; if proof needs Docker, the claim is unprovable here).
- web: vitest in apps/web (npm -w @vesta/web run test).
Tests must be deterministic: run twice, same failure both times.`

const PR_RULES = `Branch from origin/master (git fetch origin master, git checkout -b <branch> origin/master). Never weaken or delete a test to pass. Commit ending with the Co-Authored-By trailer for Claude, push -u origin, gh pr create --base master. Body: no dashes, ending with the Generated with Claude Code trailer.`

const CHECKS = { agent: './check.sh agent', cli: './check.sh cli', vestad: './check.sh vestad', web: './check.sh web' }

const LENSES = [
  { key: 'concurrency', focus: 'races, deadlocks, lost wakeups, cancellation bugs: asyncio task lifecycle in agent/core (loops.py, api.py, cc_sdk), the interrupt and compaction paths, tokio tasks and WS lifecycle in vestad' },
  { key: 'error-paths', focus: 'failure handling: partial failures, swallowed errors, missing timeouts, retry bugs, resource leaks (files, sockets, tmux sessions, docker handles), cleanup skipped on early return' },
  { key: 'boundaries', focus: 'parsing and contracts: the env config contract, notification JSON, cc_sdk transcript tailing, HTTP/WS DTOs between cli/app and vestad, edge inputs (empty, huge, unicode, concurrent writers)' },
  { key: 'state-integrity', focus: 'persistence: events.db migrations and FTS, state.json atomic writes, session resume, crash recovery, backup/restore (restic, docker import metadata), boot markers' },
  { key: 'security', focus: 'auth and injection: API key and AGENT_TOKEN handling, TLS fingerprint verification, path traversal in file-serving endpoints, command and tmux-paste injection, secrets leaking into logs' },
]

const BUGS_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
    title: { type: 'string' },
    area: { type: 'string', enum: ['agent', 'cli', 'vestad', 'web'] },
    file: { type: 'string' }, line: { type: 'number' },
    severity: { type: 'string', enum: ['low', 'medium', 'high', 'critical'] },
    bug: { type: 'string', description: 'what goes wrong and why, per the actual code' },
    trigger: { type: 'string', description: 'the concrete sequence that hits it' },
  }, required: ['title', 'area', 'file', 'severity', 'bug', 'trigger'] } } },
  required: ['findings'],
}

const PROOF_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    proven: { type: 'boolean' },
    testPath: { type: 'string' },
    testCode: { type: 'string', description: 'the full failing test source' },
    testCommand: { type: 'string' },
    observedFailure: { type: 'string', description: 'the actual failure output, abridged' },
    reason: { type: 'string' },
  }, required: ['proven', 'reason'],
}

const PLAN_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    bugs: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
      title: { type: 'string' }, area: { type: 'string', enum: ['agent', 'cli', 'vestad', 'web'] },
      file: { type: 'string' }, severity: { type: 'string', enum: ['low', 'medium', 'high', 'critical'] },
      bug: { type: 'string' }, trigger: { type: 'string' },
      testPath: { type: 'string' }, testCode: { type: 'string' }, testCommand: { type: 'string' },
      fixHint: { type: 'string', description: 'the minimal fix direction' },
    }, required: ['title', 'area', 'file', 'severity', 'bug', 'trigger', 'testPath', 'testCode', 'testCommand', 'fixHint'] } },
    droppedCount: { type: 'number' },
  }, required: ['bugs', 'droppedCount'],
}

const PR_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    label: { type: 'string' }, prUrl: { type: ['string', 'null'] },
    checksPassed: { type: 'boolean' }, note: { type: 'string' },
  }, required: ['label', 'checksPassed', 'note'],
}

// ---- Hunt: rounds of diverse finders until a round adds nothing new ----
phase('Hunt')
const seen = new Set()
const claims = []
let round = 0
while (round < MAX_ROUNDS) {
  round++
  const prior = claims.map((c) => c.title).join('; ')
  const found = (await parallel(LENSES.map((lens) => () =>
    deep(
      `Hunt for REAL bugs in this repo through one lens: ${lens.focus}.
${round > 1 ? `Round ${round}. Already claimed (hunt ELSEWHERE): ${prior}` : ''}
${NORTH_STAR}
Read CLAUDE.md first; its Architecture section describes intentional design, do not flag it. Then read the relevant code deeply. A bug is a concrete defect with a trigger sequence, not a smell or a hypothetical. Report only claims you believe would survive a reproducing test: exact file:line, what goes wrong and why per the code, the concrete trigger. No style notes. Do not edit anything. An empty findings list is a fine answer.`,
      { phase: 'Hunt', label: `hunt:${lens.key}:r${round}`, schema: BUGS_SCHEMA },
    )))).filter(Boolean).flatMap((r) => r.findings)
  const fresh = found.filter((f) => !seen.has(`${f.file}|${f.title}`))
  fresh.forEach((f) => seen.add(`${f.file}|${f.title}`))
  claims.push(...fresh)
  log(`round ${round}: ${fresh.length} new claims (${claims.length} total)`)
  if (fresh.length === 0) break
}

if (claims.length === 0) {
  log('no bug claims survived the hunt')
  return { bugsProven: 0, prs: [] }
}

// ---- Prove: a failing test or death ----
phase('Prove')
const proofs = await parallel(claims.map((claim) => () =>
  run(
    `Prove or kill this bug claim by writing a failing test in your isolated worktree.
Claim: ${JSON.stringify(claim)}
${TESTS_HOWTO}
Write the MINIMAL test that reproduces the bug, run it, confirm it fails for the claimed reason (not a setup error), then run it again: same failure twice or it does not count. If you cannot make it fail honestly (the bug is not real, needs Docker or a live agent, or is flaky), proven=false with the reason. Never return proven=true without the observed failing output.`,
    { phase: 'Prove', label: `prove:${claim.title.slice(0, 28)}`, schema: PROOF_SCHEMA, isolation: 'worktree' },
  ).then((p) => (p && p.proven ? { ...claim, ...p } : null)),
))
const proven = proofs.filter(Boolean)
log(`${proven.length}/${claims.length} claims proven by a failing test`)

if (proven.length === 0) return { claims: claims.length, bugsProven: 0, prs: [] }

// ---- Curate: dedup same-root-cause, rank, cap (needs all proofs together) ----
phase('Curate')
const plan = (await deep(
  `Curate proven bugs into fix PRs. Dedup claims sharing one root cause (keep the best test), rank by severity, cap at ${MAX_FIXES} (count the rest in droppedCount). Run \`gh pr list --state open\`: drop bugs a PR already fixes in flight; closed-unmerged fix PRs from prior runs are rejected taste, do not re-propose. For each kept bug add fixHint: the minimal fix direction, per the north star.
${NORTH_STAR}
Proven bugs: ${JSON.stringify(proven)}`,
  { phase: 'Curate', label: 'curate', schema: PLAN_SCHEMA },
)) || { bugs: [], droppedCount: 0 }
log(`${plan.bugs.length} fix PRs planned, ${plan.droppedCount} dropped`)

// ---- Fix: one PR per bug, regression test included ----
phase('Fix')
const prs = await parallel(plan.bugs.map((bug, i) => () =>
  run(
    `Fix ONE proven bug in your isolated worktree. Branch fix/bug-${i}.
Bug + proof: ${JSON.stringify(bug)}
${NORTH_STAR}
1. Recreate the regression test exactly (testPath, testCode), run ${bug.testCommand}, confirm it FAILS.
2. Implement the minimal fix (start from fixHint, trust the code over the hint). Honor repo conventions: read CLAUDE.md + CONTRIBUTING.md (functional Python, Result-returning Rust, no dashes in prose).
3. The test now passes; run ${CHECKS[bug.area]} until fully green.
4. ${PR_RULES} Title 'fix(${bug.area}): ${bug.title}'. Body: the bug, root cause, trigger, how the shipped test guards it.
If the honest fix requires a structural redesign, abort with a clear note instead of hacking around it.`,
    { phase: 'Fix', label: `fix:${bug.area}-${i}`, schema: PR_SCHEMA, isolation: 'worktree' },
  )))

const opened = prs.filter(Boolean).filter((r) => r.prUrl)
log(`Done: ${opened.length} fix PR(s) opened`)
return {
  claims: claims.length,
  bugsProven: proven.length,
  prs: opened.map((r) => ({ label: r.label, url: r.prUrl })),
  noPr: prs.filter(Boolean).filter((r) => !r.prUrl).map((r) => ({ label: r.label, note: r.note })),
  dropped: plan.droppedCount,
}

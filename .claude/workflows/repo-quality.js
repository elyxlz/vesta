export const meta = {
  name: 'repo-quality',
  description: 'Audit each area against the in-repo rubric (CLAUDE.md + CONTRIBUTING.md) and the elegance north star; open a surgical PR per area plus, when truly warranted, one ambitious simplification PR',
  whenToUse: 'Recurring quality pass: conform code to the codified standards, hunt net-deletion simplifications.',
  phases: [
    { title: 'Audit', detail: 'area x dimension finders' },
    { title: 'Curate', detail: 'dedup, verify, select surgical batch + at most one ambitious move' },
    { title: 'Implement', detail: 'worktree PRs, checks green' },
  ],
}

// fable for judgment nothing downstream can recover; sonnet where the curator/checks catch mistakes.
const deep = (prompt, opts) => agent(prompt, { model: 'fable', ...opts })
const run = (prompt, opts) => agent(prompt, { model: 'sonnet', ...opts })

const NORTH_STAR = `NORTH STAR: elegance. 90% of the value for 10% of the effort. Be bold in scope, ruthless in the result: re-architect freely, but the code must END SIMPLER (fewer concepts, fewer lines, fewer branches). Subtraction beats addition; the best change is a deletion. A complex final diff is failure, not ambition.`

const RULES = `Rubric: read root CLAUDE.md (Architecture Principles) and CONTRIBUTING.md (code conventions, Karpathy Guidelines) first; they override external canon. Hard rules: functional Python (no getattr, no dict .get fallback, no hasattr, no classes-with-methods, no silent exception swallowing); Rust returns Result (no panic/unwrap/expect on fallible paths), named constants, minimal clone; web says 'agent' never 'box'; prose has no dashes; never bump versions; surgical diffs matching surrounding style.`

const PR_RULES = `Branch from origin/master (git fetch origin master, git checkout -b <branch> origin/master). Never weaken or delete a test to pass. Commit ending with the Co-Authored-By trailer for Claude, push -u origin, gh pr create --base master. Body: what and why, no dashes, ending with the Generated with Claude Code trailer.`

const AREAS = [
  { key: 'agent', root: 'agent', check: './check.sh agent',
    scope: 'async Python agent: core/loops.py, cc_sdk/, api.py, config.py, skills' },
  { key: 'cli', root: 'cli', check: './check.sh cli',
    scope: 'vesta client CLI crate (Rust, HTTPS to vestad)' },
  { key: 'vestad', root: 'vestad/src', check: './check.sh vestad',
    scope: 'vestad daemon crate: docker.rs, HTTP+WS API, restic backup, auth/TLS' },
  { key: 'web', root: 'apps/web/src', check: './check.sh web',
    scope: 'React SPA: components/, providers/, hooks/' },
]

const DIMENSIONS = [
  { key: 'elegance', focus: 'the 90/10 move: code that could be half the length, abstractions that should disappear or inline, duplication that collapses into one owner, net-deletion simplifications that preserve behavior' },
  { key: 'quality', focus: 'readability, naming, dead code, inconsistent patterns, comment quality, idiom mismatches' },
  { key: 'reliability', focus: 'error handling, edge cases, races, resource leaks, silent failures, Rust unwrap/panic, Python swallowed errors' },
  { key: 'complexity', focus: 'overly long functions, deep nesting, god modules, tangled control flow; complexity to isolate behind a clean boundary' },
]

const FINDINGS_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
    title: { type: 'string' }, file: { type: 'string' }, line: { type: 'number' },
    dimension: { type: 'string' }, severity: { type: 'string', enum: ['low', 'medium', 'high'] },
    fixRisk: { type: 'string', enum: ['low', 'medium', 'high'] },
    rationale: { type: 'string' }, suggestedFix: { type: 'string' },
  }, required: ['title', 'file', 'severity', 'fixRisk', 'rationale', 'suggestedFix'] } } },
  required: ['findings'],
}

const SELECTION_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    theme: { type: 'string' },
    selected: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
      title: { type: 'string' }, file: { type: 'string' }, line: { type: 'number' },
      rationale: { type: 'string' }, fix: { type: 'string' },
    }, required: ['title', 'file', 'rationale', 'fix'] } },
    ambitious: { type: ['object', 'null'], additionalProperties: false,
      description: 'at most ONE structural simplification deserving its own PR; null unless truly warranted',
      properties: {
        title: { type: 'string' },
        files: { type: 'array', items: { type: 'string' } },
        rationale: { type: 'string' },
        plan: { type: 'string', description: 'what disappears, what replaces it, how behavior is proven preserved' },
      }, required: ['title', 'files', 'rationale', 'plan'] },
    droppedCount: { type: 'number' },
  }, required: ['theme', 'selected', 'ambitious'],
}

const PR_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    label: { type: 'string' }, branch: { type: ['string', 'null'] }, prUrl: { type: ['string', 'null'] },
    checksPassed: { type: 'boolean' }, changesSummary: { type: 'string' },
    filesChanged: { type: 'array', items: { type: 'string' } }, note: { type: 'string' },
  }, required: ['label', 'checksPassed', 'changesSummary', 'note'],
}

const areaResults = await pipeline(
  AREAS,
  // Audit: one finder per dimension, whole-area scan
  (area) =>
    parallel(DIMENSIONS.map((dim) => () =>
      run(
        `Audit ${area.root} (${area.scope}) for ${dim.key}: ${dim.focus}.
${RULES}
${NORTH_STAR}
Scan the whole area, largest and most central modules first. Findings only: exact file:line, severity, fixRisk, crisp rationale, concrete suggestedFix. The best finding is usually a deletion; high fixRisk is fine when the payoff is real. Do not edit.`,
        { phase: 'Audit', label: `audit:${area.key}:${dim.key}`, schema: FINDINGS_SCHEMA },
      ),
    )).then((rs) => ({ area, findings: rs.filter(Boolean).flatMap((r) => r.findings) })),
  // Curate: dedup, verify against the real code, select
  (prev) =>
    deep(
      `Curate quality PRs for '${prev.area.key}' (root ${prev.area.root}).
${NORTH_STAR}
From the findings below: dedup, then verify each by reading the cited code; keep only what is real and net-positive. Run \`gh pr list --state open\` first: drop findings an open PR already addresses; closed-unmerged PRs from prior runs are rejected taste, do not re-propose them. Select up to 6 self-contained fixes for ONE surgical themed PR, each with a precise fix instruction. Separately pick at most ONE ambitious structural simplification, only if truly needed: high conviction, behavior provable by ${prev.area.check}, meaningfully simpler after (ideally net-negative lines). Most runs: ambitious=null.
Findings: ${JSON.stringify(prev.findings)}`,
      { phase: 'Curate', label: `curate:${prev.area.key}`, schema: SELECTION_SCHEMA },
    ).then((sel) => ({ area: prev.area, theme: sel ? sel.theme : '', selected: sel ? sel.selected : [], ambitious: sel ? sel.ambitious : null })),
  // Implement: surgical PR + optional ambitious PR, each in its own worktree
  (prev) => {
    const surgical = () =>
      prev.selected.length === 0
        ? Promise.resolve({ label: prev.area.key, checksPassed: true, prUrl: null, branch: null, filesChanged: [],
            changesSummary: 'nothing selected', note: 'no surgical PR for this area' })
        : run(
            `Open the surgical quality PR for '${prev.area.key}' in your worktree. Branch chore/quality-${prev.area.key}. Theme: ${prev.theme}.
${RULES}
Apply ONLY these changes, reading each file first; drop any change that cannot pass cleanly. Run ${prev.area.check} until green.
${PR_RULES} Title 'refactor(${prev.area.key}): <short theme>'.
Changes: ${JSON.stringify(prev.selected)}
Return label='${prev.area.key}', prUrl, branch, checksPassed, filesChanged, changesSummary, note. No PR if nothing lands (checksPassed=false, clear note).`,
            { phase: 'Implement', label: `pr:${prev.area.key}`, isolation: 'worktree', schema: PR_SCHEMA },
          )
    const ambitious = () =>
      !prev.ambitious
        ? Promise.resolve(null)
        : deep(
            `Land ONE ambitious simplification for '${prev.area.key}' in your worktree. Branch refactor/${prev.area.key}-simplify.
${NORTH_STAR}
${RULES}
Plan: ${JSON.stringify(prev.ambitious, null, 2)}
Re-architect as boldly as the plan needs, but behavior is preserved: existing tests pass unchanged (add one only at an untested seam). Run ${prev.area.check} until green. Before opening, re-read the full diff: if the result is not clearly simpler, ABORT with a note (a good outcome, not a failure).
${PR_RULES} Title 'refactor(${prev.area.key}): ${prev.ambitious.title}'; body quantifies lines removed vs added.
Return label='${prev.area.key}-ambitious', prUrl, branch, checksPassed, filesChanged, changesSummary, note.`,
            { phase: 'Implement', label: `pr:${prev.area.key}-ambitious`, isolation: 'worktree', schema: PR_SCHEMA },
          )
    return parallel([surgical, ambitious])
  },
)

const all = areaResults.flat().filter(Boolean)
const opened = all.filter((r) => r.prUrl)
log(`Done: ${opened.length} PR(s) opened`)
return {
  prsOpened: opened.map((r) => ({ label: r.label, url: r.prUrl, summary: r.changesSummary })),
  noPr: all.filter((r) => !r.prUrl).map((r) => ({ label: r.label, checksPassed: r.checksPassed, note: r.note })),
}

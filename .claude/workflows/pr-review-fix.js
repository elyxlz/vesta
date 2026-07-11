export const meta = {
  name: 'pr-review-fix',
  description: 'Code-review every open non-draft PR, adversarially verify each finding, then push the confirmed fixes to each PR branch',
  whenToUse: 'Recurring PR hygiene pass: review + integrate fixes across all active PRs. Pass args = [{number, title, branch}] from gh pr list (non-draft).',
  phases: [
    { title: 'Review', detail: 'one reviewer per PR, merge-blocking defects only' },
    { title: 'Verify', detail: 'one adversarial verifier per finding' },
    { title: 'Fix', detail: 'worktree agent per PR, checks green, push to the PR branch' },
  ],
}

const fable = (prompt, opts) => agent(prompt, { model: 'fable', ...opts })

const RULES = `Rubric: read root CLAUDE.md (Architecture Principles, code conventions, Karpathy Guidelines) first; it overrides external canon. Hard rules: functional Python (no getattr, no dict .get fallback, no hasattr, no classes-with-methods, no tp.Any/object loose typing, no silent exception swallowing); Rust returns Result (no panic/unwrap/expect on fallible paths), named constants, minimal clone; web says 'agent' never 'box'; prose has no dashes and Vesta is never 'she' or 'it'; never bump versions; tests ship with logic changes; skills index regenerated when SKILL.md frontmatter changes.`

const BRANCH_READ = `The PR branch may be checked out in another local worktree, so never check out the branch by name. To read branch code: git fetch origin <branch>, then git show FETCH_HEAD:<path> (or git diff master...FETCH_HEAD).`

const CHECK_MAP = `Map changed paths to checks (run every one that applies, from the repo root): agent/ -> ./check.sh agent, cli/ -> ./check.sh cli, vestad/ -> ./check.sh vestad, apps/web/ -> ./check.sh web. If a SKILL.md name/description changed, run uv run python agent/skills/generate-index.py and commit agent/skills/index.json.`

const FINDINGS_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
    title: { type: 'string' }, file: { type: 'string' }, line: { type: ['number', 'null'] },
    severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
    issue: { type: 'string' }, fix: { type: 'string' },
  }, required: ['title', 'file', 'severity', 'issue', 'fix'] } } },
  required: ['findings'],
}

const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { real: { type: 'boolean' }, reason: { type: 'string' } },
  required: ['real', 'reason'],
}

const FIX_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    number: { type: 'number' }, pushed: { type: 'boolean' }, checksPassed: { type: 'boolean' },
    fixedCount: { type: 'number' }, droppedCount: { type: 'number' },
    summary: { type: 'string' }, note: { type: 'string' },
  }, required: ['number', 'pushed', 'checksPassed', 'fixedCount', 'droppedCount', 'summary', 'note'],
}

const prs = typeof args === 'string' ? JSON.parse(args) : args

const results = await pipeline(
  prs,
  (pr) =>
    fable(
      `Code-review PR #${pr.number} "${pr.title}" (branch ${pr.branch}) in this repo. Read-only: do NOT edit anything.
${RULES}
${BRANCH_READ}
Read the full PR: gh pr view ${pr.number}, gh pr diff ${pr.number}, plus enough surrounding branch code to judge each hunk in context.
Report ONLY defects worth blocking a merge on, introduced or left unresolved by this diff: real bugs (wrong logic, races, leaks, broken edge cases), violations of the codified rules above, logic changes shipping without tests, changes that will fail CI, and fleet hazards (on-disk/config state moved without a migration). NOT taste, NOT style beyond the codified rules, NOT pre-existing issues the diff does not touch. An empty findings list is a good outcome. Each finding: exact file and line on the PR branch, crisp issue, concrete fix instruction.`,
      { phase: 'Review', label: `review:${pr.number}`, schema: FINDINGS_SCHEMA },
    ).then((r) => ({ pr, findings: r ? r.findings : [] })),
  (prev) =>
    prev.findings.length === 0
      ? Promise.resolve({ pr: prev.pr, confirmed: [] })
      : parallel(prev.findings.map((f) => () =>
          fable(
            `Adversarially verify one code-review finding on PR #${prev.pr.number} (branch ${prev.pr.branch}). Try hard to REFUTE it; real=true only if it survives. Read-only.
${BRANCH_READ}
Check the finding against the actual branch code and the actual diff (gh pr diff ${prev.pr.number}): is the defect really there, really introduced/owned by this PR, and really worth blocking a merge? A rule violation must cite a rule codified in root CLAUDE.md. If uncertain, real=false.
Finding: ${JSON.stringify(f)}`,
            { phase: 'Verify', label: `verify:${prev.pr.number}`, schema: VERDICT_SCHEMA },
          ).then((v) => (v && v.real ? { ...f, verified: v.reason } : null)),
        )).then((vs) => ({ pr: prev.pr, confirmed: vs.filter(Boolean) })),
  (prev) =>
    prev.confirmed.length === 0
      ? Promise.resolve({ number: prev.pr.number, pushed: false, checksPassed: true, fixedCount: 0, droppedCount: 0,
          summary: 'clean review', note: 'no confirmed findings, branch untouched' })
      : fable(
          `Integrate confirmed code-review fixes into PR #${prev.pr.number} "${prev.pr.title}" (branch ${prev.pr.branch}). Work in your worktree only.
${RULES}
${BRANCH_READ} Set up with: git fetch origin ${prev.pr.branch} && git checkout --detach FETCH_HEAD.
Apply each confirmed fix below, reading the real code first; if a fix turns out wrong or already addressed, drop it (count it in droppedCount) rather than forcing it. Never weaken or delete a test to pass. ${CHECK_MAP} Run the applicable checks until green.
If anything landed: commit (Conventional Commits subject describing the fixes, imperative, ending with the Co-Authored-By trailer for Claude), push with git push origin HEAD:${prev.pr.branch} (NEVER force push), then comment on the PR via gh pr comment ${prev.pr.number} summarizing what was fixed and why (no dashes in prose, end with the Generated with Claude Code trailer). If nothing lands, push nothing and say why in note.
Confirmed findings: ${JSON.stringify(prev.confirmed)}`,
          { phase: 'Fix', label: `fix:${prev.pr.number}`, isolation: 'worktree', schema: FIX_SCHEMA },
        ),
)

const all = results.filter(Boolean)
const pushed = all.filter((r) => r.pushed)
log(`Done: ${pushed.length}/${all.length} PRs received fixes`)
return {
  fixed: pushed.map((r) => ({ pr: r.number, fixed: r.fixedCount, dropped: r.droppedCount, checksPassed: r.checksPassed, summary: r.summary })),
  clean: all.filter((r) => !r.pushed && r.checksPassed).map((r) => ({ pr: r.number, note: r.note })),
  problems: all.filter((r) => !r.pushed && !r.checksPassed).map((r) => ({ pr: r.number, note: r.note })),
}

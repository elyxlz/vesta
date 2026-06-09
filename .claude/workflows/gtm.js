export const meta = {
  name: "gtm",
  description:
    "Audit the entire stranger-to-paying-user funnel (positioning, landing, pricing, onboarding, emails, referral) across vesta + vesta-cloud against exemplar GTM; copy/design fixes -> PRs in the right repo, strategy forks -> issues + a strategy doc.",
  whenToUse:
    "Recurring go-to-market pass. Needs ../vesta-cloud checked out locally. Default emit=draft writes .critique/gtm/ for review; args {emit:'live'} opens PRs and issues.",
  phases: [
    { title: "Audit", detail: "5 funnel stages, walked as a skeptical buyer" },
    { title: "Verify", detail: "refute each finding" },
    { title: "Synthesize", detail: "positioning, route PRs/issues, strategy doc" },
    { title: "Emit", detail: "drafts or live cross-repo PRs + issues" },
  ],
};

// fable for buyer-judgment and positioning; sonnet for refutation and check-verified copy PRs; haiku for I/O chores.
const deep = (prompt, opts) => agent(prompt, { model: "fable", ...opts });
const run = (prompt, opts) => agent(prompt, { model: "sonnet", ...opts });
const fast = (prompt, opts) => agent(prompt, { model: "haiku", ...opts });

const EMIT = (args && args.emit) || "draft";
const CLOUD = "/home/elyx/Repos/vesta-cloud";

const BUSINESS = `The business: vesta.run sells a hosted personal AI agent. Open-core: the data plane (this repo, elyxlz/vesta: vestad daemon + CLI + apps) is open source; the control plane (${CLOUD}, elyxlz/vesta-cloud: marketing SPA + dashboard + Stripe billing + per-user Hetzner VM provisioning + referral rewards) is closed. The buyer is a consumer/prosumer who wants a personal AI living in their life (WhatsApp, Telegram, email, calendar), not a dev tool. Indie income, not venture scale; the moat is doing what the labs cannot.`;

const VOICE = `Brand voice (intentional, never "fix"): lowercase, terse, human; no em/en dashes or " - " separators (CI enforces this in both repos; use commas/colons); "agent" never "box".`;

const NORTH_STAR = `NORTH STAR: elegance. 90% of the value for 10% of the effort. The best GTM fix usually removes: a step, a claim, a paragraph, a decision. One sharp sentence beats three feature lists. Sweat the details: a stranger decides in seconds. A busier page or longer funnel is failure, not ambition.`;

const FUNNEL = [
  {
    key: "discover",
    stage: "Discover: first impression and positioning",
    surfaces: `vesta.run landing + marketing pages (${CLOUD}/src/pages, ${CLOUD}/index.html), elyxlz/vesta README.md, the one-liner wherever it appears (repo description, app copy)`,
    mandate: "Does a stranger get what Vesta is, who it is for, and why it beats ChatGPT-in-a-tab within 10 seconds? Is the one-liner sharp and consistent everywhere? Does the page sell the feeling (a personal presence in your life) or list features?",
  },
  {
    key: "evaluate",
    stage: "Evaluate: trust, pricing, objections",
    surfaces: `pricing page + plan copy (${CLOUD}/src), legal pages (${CLOUD}/legal), the privacy/open-source story, FAQ or its absence, README architecture/trust sections`,
    mandate: "Walk the buyer's objections: price vs value framing, what happens to my data, why a dedicated VM matters, can I leave (export/self-host), is this maintained? Each objection answered where it arises, or the buyer leaves silently.",
  },
  {
    key: "convert",
    stage: "Convert: signup to provisioned",
    surfaces: `signup/checkout/onboarding flow (${CLOUD}/functions/api, ${CLOUD}/functions/auth, ${CLOUD}/src dashboard states), transactional emails (${CLOUD}/functions/lib/email.ts), the provisioning wait, the self-host alternative (install.sh + vestad first run in this repo)`,
    mandate: "Count every field, click, paste, wait, and decision between intent and a live agent. Where does momentum die? Is the provisioning wait honest and warm or a silent spinner? Do the emails arrive at the right moments and sound like the brand?",
  },
  {
    key: "activate",
    stage: "Activate: first session to aha",
    surfaces: `first chat and channel setup (apps/web onboarding wizard in this repo, the connect flows, WhatsApp/Telegram pairing skills), the first-wake experience, time-to-first-value`,
    mandate: "The aha is Vesta acting in YOUR life (messages, calendar, memory), not answering a test prompt. How fast does a new user reach it? What is the designed emotional peak of day one, and the ending (Peak-End)?",
  },
  {
    key: "retain-refer",
    stage: "Retain and refer",
    surfaces: `referral program presentation (${CLOUD}), grace-period/dunning emails (${CLOUD}/functions/lib/email.ts, crons), release notes and update communication, the reasons to stay after week one`,
    mandate: "Why does month two feel worth it? Does the product communicate growth (what Vesta learned, did, prevented)? Is the referral ask placed at a moment of delight? Are the churn-moment emails graceful and human?",
  },
];

const FINDINGS_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["stage", "findings"],
  properties: {
    stage: { type: "string" },
    findings: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "surface", "repo", "problem", "proposal", "kind", "impact", "effort"],
        properties: {
          title: { type: "string" },
          surface: { type: "string" },
          repo: { type: "string", enum: ["vesta", "vesta-cloud"] },
          file: { type: "string", description: "file:line where known" },
          problem: { type: "string", description: "the funnel leak, as the buyer experiences it" },
          before: { type: "string", description: "current copy/behavior" },
          proposal: { type: "string", description: "concrete change; for copy, the exact new words" },
          kind: { type: "string", enum: ["copy", "design", "strategy"] },
          impact: { type: "string", enum: ["low", "medium", "high"] },
          effort: { type: "string", enum: ["trivial", "small", "medium", "large"] },
        },
      },
    },
  },
};

const VERDICT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["keep", "isReal", "fixIsBetter", "reason"],
  properties: {
    keep: { type: "boolean" },
    isReal: { type: "boolean", description: "a genuine funnel leak, not marketer taste" },
    fixIsBetter: { type: "boolean", description: "sharper and simpler, not just different; respects the brand voice" },
    reason: { type: "string" },
  },
};

const SYNTH_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["positioning", "top10", "prGroups", "issues", "strategyMarkdown", "reportMarkdown"],
  properties: {
    positioning: { type: "string", description: "the one-liner + a 3-sentence narrative" },
    top10: {
      type: "array",
      items: {
        type: "object", additionalProperties: false, required: ["title", "why"],
        properties: { title: { type: "string" }, why: { type: "string" } },
      },
    },
    prGroups: {
      type: "array",
      description: "one PR each, in the right repo; copy/design fixes fully specified",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "repo", "summary", "changes"],
        properties: {
          title: { type: "string", description: "conventional-commit style" },
          repo: { type: "string", enum: ["vesta", "vesta-cloud"] },
          summary: { type: "string" },
          changes: { type: "array", items: { type: "string", description: "file -> before -> after" } },
        },
      },
    },
    issues: {
      type: "array",
      description: "strategy forks the user must decide (pricing, naming, channels)",
      items: {
        type: "object", additionalProperties: false, required: ["title", "repo", "labels", "body"],
        properties: {
          title: { type: "string" },
          repo: { type: "string", enum: ["vesta", "vesta-cloud"] },
          labels: { type: "array", items: { type: "string" } },
          body: { type: "string" },
        },
      },
    },
    strategyMarkdown: { type: "string", description: "the GTM strategy doc: positioning, funnel diagnosis, channel/pricing recommendations with reasoning" },
    reportMarkdown: { type: "string", description: "the full findings report" },
  },
};

// ── Audit ────────────────────────────────────────────────────────────────────
const verified = await pipeline(
  FUNNEL,
  (f) =>
    deep(
      `You are a world-class GTM critic walking ONE funnel stage as a skeptical prospective buyer.
Stage: ${f.stage}
Surfaces to walk (read the real files): ${f.surfaces}
Mandate: ${f.mandate}
${BUSINESS}
${VOICE}
${NORTH_STAR}
Ground in exemplars: fetch how Linear, Raycast, Tailscale, and Superhuman handle this stage if useful, but judge against what fits an indie personal-AI product, not a venture SaaS. File 5-10 high-signal findings: the leak as the buyer feels it, exact file where known, concrete proposal (for copy: the exact new words, in the brand voice). kind: copy = words/strings; design = layout/flow needing visual judgment; strategy = a fork the user must decide (pricing, naming, channels).`,
      { label: `audit:${f.key}`, phase: "Audit", schema: FINDINGS_SCHEMA },
    ),
  (result, f) => {
    if (!result || !result.findings || !result.findings.length) return [];
    return parallel(
      result.findings.map((finding) => () =>
        run(
          `Refute this GTM finding; most marketing notes are taste, not leaks.
${JSON.stringify(finding)}
${VOICE}
${NORTH_STAR}
keep=true only if it is a real funnel leak a buyer would actually hit AND the proposal is sharper and simpler (not louder, longer, or busier) AND it respects the brand voice. Verify the cited file exists where given. Unsure -> keep=false.`,
          { label: `verify:${f.key}:${finding.title.slice(0, 22)}`, phase: "Verify", schema: VERDICT_SCHEMA },
        ).then((v) => ({ ...finding, stage: f.key, verdict: v })),
      ),
    );
  },
);

const kept = verified.flat().filter(Boolean).filter((f) => f.verdict && f.verdict.keep);
log(`${kept.length} findings survived refutation`);

// ── Synthesize ───────────────────────────────────────────────────────────────
phase("Synthesize");
const synth = await deep(
  `Synthesize the GTM report from these verified findings.
${JSON.stringify(kept, null, 2)}
${BUSINESS}
${VOICE}
${NORTH_STAR}
1. Write positioning: the one-liner + 3-sentence narrative everything else should align to.
2. Dedup/cluster. Run \`gh pr list --state open\` and \`gh pr list -R elyxlz/vesta-cloud --state open\`: drop what is in flight. Route: copy and well-specified design fixes -> prGroups (one coherent PR each, exact file -> before -> after, tagged with the right repo). Strategy forks (pricing, naming, channel bets) -> issues in the right repo; these need the user.
3. top10 highest-leverage moves.
4. strategyMarkdown: the GTM strategy doc (positioning, funnel diagnosis per stage, channel and pricing recommendations with reasoning, what NOT to do).
5. reportMarkdown: the findings report.`,
  { label: "synthesize", phase: "Synthesize", schema: SYNTH_SCHEMA },
);

// ── Emit ─────────────────────────────────────────────────────────────────────
phase("Emit");
await fast(
  `Write with the Write tool and confirm paths:
- .critique/gtm/STRATEGY.md = exactly:\n---\n${synth.strategyMarkdown}\n---
- .critique/gtm/REPORT.md = exactly:\n---\n${synth.reportMarkdown}\n---
- .critique/gtm/prs.json = ${JSON.stringify(synth.prGroups)}
- .critique/gtm/issues.json = ${JSON.stringify(synth.issues)}`,
  { label: "write-drafts", phase: "Emit" },
);

if (EMIT !== "live") {
  return {
    mode: "draft",
    positioning: synth.positioning,
    findings: kept.length,
    prGroups: synth.prGroups.length,
    issues: synth.issues.length,
    strategy: ".critique/gtm/STRATEGY.md",
  };
}

log(`live emit: ${synth.prGroups.length} PRs, ${synth.issues.length} issues`);

const prs = await parallel(
  synth.prGroups.map((group, i) => () =>
    run(
      `Open ONE GTM PR for repo ${group.repo}.
Group: ${JSON.stringify(group)}
${VOICE}
${NORTH_STAR}
${group.repo === "vesta-cloud"
        ? `This targets vesta-cloud, manage your own worktree there:
1. git -C ${CLOUD} fetch origin master && git -C ${CLOUD} worktree add /tmp/gtm-${i} -b gtm/${i} origin/master
2. Work in /tmp/gtm-${i}: npm install, apply ONLY the listed changes (adapt minimally where the spec misses current code), run ./check.sh all until green.
3. Commit (Co-Authored-By trailer), git push -u origin gtm/${i}, gh pr create --base master (run gh from /tmp/gtm-${i}).
4. Cleanup: git -C ${CLOUD} worktree remove --force /tmp/gtm-${i}.`
        : `This targets this repo (you are in an isolated worktree):
1. git fetch origin master && git checkout -b gtm/${i} origin/master
2. Apply ONLY the listed changes. Run the check.sh suite for whatever you touched (web/cli/agent); markdown-only edits rely on CI.
3. Commit (Co-Authored-By trailer), push -u, gh pr create --base master.`}
No version bumps. PR title "${group.title}"; body: the funnel leak and the rationale, ending with the Generated with Claude Code line.
Return the PR url or an error string.`,
      { label: `pr:${group.repo}-${i}`, phase: "Emit", isolation: group.repo === "vesta" ? "worktree" : undefined },
    ),
  ),
);

const issues = await parallel(
  synth.issues.map((issue, i) => () =>
    fast(
      `Open a GitHub issue on elyxlz/${issue.repo}: \`gh issue create -R elyxlz/${issue.repo} --title ${JSON.stringify(issue.title)} --body <body>\`, applying only labels that already exist there (gh label list -R elyxlz/${issue.repo}). Body:\n${issue.body}\nReturn the issue url.`,
      { label: `issue:${issue.repo}-${i}`, phase: "Emit" },
    ),
  ),
);

return {
  mode: "live",
  positioning: synth.positioning,
  findings: kept.length,
  prs: prs.filter(Boolean),
  issues: issues.filter(Boolean),
  strategy: ".critique/gtm/STRATEGY.md",
};

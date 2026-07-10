export const meta = {
  name: "product-critique",
  description:
    "Frontier product/design critique of the Vesta app (visuals, interaction, onboarding, copy, a11y). Every truly-needed fix -> PR drafts (cheap or ambitious); only genuine design forks -> issue drafts. Vesta's voice/personality is out of scope.",
  whenToUse:
    "Holistic design/UX pass on the Vesta app and onboarding journey. Run after capturing screenshots with tools/critique/capture-ui.mjs. Opens PRs and issues by default; args {emit:'draft'} writes .critique/out/ for review instead, {emit:'publish'} skips the critique and emits PRs from the saved draft.",
  phases: [
    { title: "Load", detail: "publish mode: read the saved PR groups" },
    { title: "Brief", detail: "list captured shots" },
    { title: "Critique", detail: "9 authority-grounded lenses, parallel" },
    { title: "Verify", detail: "adversarially refute each finding" },
    { title: "Synthesize", detail: "dedupe, rank, route" },
    { title: "Emit", detail: "drafts or live PRs/issues" },
  ],
};

// fable for judgment nothing downstream can recover; sonnet where gates/checks catch mistakes; haiku for I/O chores.
const deep = (prompt, opts) => agent(prompt, { model: "fable", ...opts });
const run = (prompt, opts) => agent(prompt, { model: "sonnet", ...opts });
const fast = (prompt, opts) => agent(prompt, { model: "haiku", ...opts });

const SHOTS_DIR = (args && args.shotsDir) || ".critique/shots";
const EMIT = (args && args.emit) || "live"; // "live" | "draft" | "publish"
const REPO = (args && args.repo) || "elyxlz/vesta";
const HIG_DIGEST = "tools/critique/apple-hig.md"; // distilled Apple HIG rulebook; regenerate when Apple ships major HIG updates

// ── shared context baked in so lenses stay grounded, never generic ──────────

const SURFACE_MAP = `
Vesta web app: apps/web/src (React + Tailwind + shadcn/base-ui + Framer Motion).
Tokens: apps/web/src/index.css (oklch colors, --rounded-squircle-*, Public Sans body / Outfit headings, --page-padding-x). Copy is INLINE in components, no i18n file.

Screens (route -> code):
- /connect            components/Connect/index.tsx            host + api key form, error details toggle
- /                   components/Home/index.tsx               AgentsCarousel or EmptyState ("no agents found")
- /new                components/NewAgent/                    wizard: NameStep -> PersonalityStep -> CreatingStep (fake rotating progress) -> AuthStep (OAuth copy/paste) -> DoneStep ("{name} is ready / say hi.")
- /agent/:name        components/Dashboard + Chat            desktop split-pane vs mobile swipe; AgentIsland + Orb (alive/thinking/booting/dead...)
- /agent/:name/chat   components/Chat/                       ChatBubble, ChatComposer, BottomBanner, ToolCallLabel
- /agent/:name/logs   components/Console/                    live log stream
- /agent/:name/settings components/AgentSettings/            actions, files+editor, keybinds, voice, memory, plan usage
- Settings dialog     components/Settings/index.tsx           theme, chat pacing, mode, gateway status, logout
- /debug              pages/Debug/index.tsx                  showcase: all orb states + every chat-bubble/markdown variant (backend-free)

Journey beyond the app (terminal copy worth critiquing):
- install.sh                          one-line installer output
- vestad first run (vestad/src/serve.rs, systemd.rs)  prints tunnel url + key + manage commands
- cli/src/main.rs                     "vesta" welcome, "vesta setup", "vesta connect", OAuth paste-code prompts
- first build wait: 5-10 min on first agent create (git clone + npm + vite build)
`;

// Vesta's deliberate choices. Findings that "correct" these are INVALID.
const STYLE_GUARD = `
INTENTIONAL, DO NOT FLAG AS BUGS:
- UI + agent copy is intentionally all-lowercase, texting-feel, terse.
- No em dashes, en dashes, or " - " as a separator anywhere. Use commas/periods/colons. (A finding that adds dashes is wrong.)
- Terminology is "agent", never "box".
- oklch palette, squircle radii, Public Sans + Outfit are the chosen design language.
OUT OF SCOPE (separate workflow): Vesta's personality, voice, prompt content, proactivity tuning, the 6 personality presets. Do not critique what Vesta *says* as a character; only how the *app* presents, formats, and supports it.
`;

const NORTH_STAR = `
NORTH STAR: elegance. 90% of the value for 10% of the effort. Be bold in scope, ruthless in the result: redesign freely, but the surface must END SIMPLER (fewer steps, states, strings, concepts). Subtraction beats addition. Sweat the last 1%: alignment, easing, copy rhythm, error tone. A busier final design is failure, not ambition.
`;

const LENSES = [
  {
    key: "visual-craft",
    title: "Visual craft & hierarchy",
    authority: "Apple Human Interface Guidelines + Refactoring UI (Wathan/Schoger)",
    url: "https://developer.apple.com/design/human-interface-guidelines/layout",
    hig: "Layout, Typography, Color, Dark Mode, Materials, Icons, Images",
    mandate:
      "Spacing rhythm, type scale & weight, color usage, contrast, depth/elevation, alignment, density, optical balance, the orb/squircle treatment, empty states. Judge the rendered pixels in the shots first, then trace to tokens in index.css / className.",
  },
  {
    key: "interaction-motion",
    title: "Interaction & motion",
    authority: "Rauno Freiberg Web Interface Guidelines + Emil Kowalski + Laws of UX",
    url: "https://interfaces.rauno.me/",
    hig: "Motion, Feedback, Loading, Launching, Gestures, Keyboards, Focus and selection, Pointing devices, Components",
    mandate:
      "Hover/focus/active/disabled states, focus rings, keyboard paths, touch-target size, easing & duration, anticipation/follow-through, optimistic UI, perceived latency (Doherty threshold), loading vs skeleton, the CreatingStep's fake rotating progress vs honest status, transitions between dashboard/chat.",
  },
  {
    key: "heuristics",
    title: "Usability heuristics",
    authority: "Nielsen's 10 Heuristics + Norman (DOET)",
    url: "https://www.nngroup.com/articles/ten-usability-heuristics/",
    hig: "Feedback, Modality, Alerts, Undo and redo, Settings, Searching",
    mandate:
      "Cite the specific heuristic per finding. Visibility of system status, match to mental model, user control/undo, consistency, error prevention, recognition over recall, flexibility, minimalist design, error recovery, help. The OAuth copy-paste and the long first-build wait are prime targets.",
  },
  {
    key: "onboarding-friction",
    title: "Onboarding & friction (time-to-value)",
    authority: "Fogg B=MAP + Growth.Design + Kathy Sierra (Badass) + Peak-End rule",
    url: "https://www.nngroup.com/articles/onboarding-tutorials/",
    hig: "Onboarding, Launching, Entering data, Managing accounts, Offering help",
    mandate:
      "Walk install -> vestad run -> connect -> create agent -> auth -> first chat as a new user. Every paste, wait, decision, and dead-end. Reduce activation energy, shorten time-to-first-value, design the emotional peak and the ending. Include the CLI/vestad terminal copy in SURFACE_MAP.",
  },
  {
    key: "agent-ux-trust",
    title: "Agent UX in the app: status, trust, errors",
    authority: "Google PAIR People+AI Guidebook + Microsoft HAX guidelines",
    url: "https://pair.withgoogle.com/guidebook/",
    hig: "Feedback, Loading, Notifications, Alerts",
    mandate:
      "How the APP (not Vesta's voice) sets expectations, shows what the agent is doing (orb/island states, tool calls, thinking), calibrates trust, handles agent errors/offline/auth-expired, and lets the user steer/interrupt. Mental model of what an 'agent' is on first contact.",
  },
  {
    key: "copy-writing",
    title: "Copy / UX writing",
    authority: "Mailchimp Content Style Guide + Apple Style Guide + Microcopy (Yifrah)",
    url: "https://www.nngroup.com/articles/ux-writing-study-guide/",
    hig: "Writing, Alerts, Offering help, Inclusion",
    mandate:
      "Every on-screen + CLI string: buttons (verbs), empty states, errors, placeholders, toasts, the wizard, vestad terminal output. Clarity, concreteness, consistency, helpful errors. Respect the intentional lowercase/no-dashes/texting voice (STYLE_GUARD): improve within it, never against it.",
  },
  {
    key: "accessibility",
    title: "Accessibility",
    authority: "WCAG 2.2 AA + Apple accessibility HIG",
    url: "https://www.w3.org/WAI/WCAG22/quickref/",
    hig: "Accessibility, Inclusion, Typography, Color, Components",
    mandate:
      "Color contrast (check oklch tokens in both themes), focus visibility & order, keyboard operability, touch-target minimums, semantic roles/labels for icon buttons, reduced-motion, screen-reader names for the orb/island/status. Cite the WCAG SC number.",
  },
  {
    key: "elegance-reduction",
    title: "Elegance & reduction",
    authority: "Dieter Rams (less, but better) + Tufte (data-ink ratio) + Tesler's law + the Jobs/Ive subtraction ethos",
    url: "https://www.interaction-design.org/literature/article/dieter-rams-10-timeless-commandments-for-good-design",
    hig: "Settings, Branding, Onboarding, Modality",
    mandate:
      "Hunt for what to REMOVE: steps in the wizard, decisions, states, settings, copy, chrome, concepts the user must hold. Where does the app make the user carry complexity the product could absorb or delete? 'Delete this' is a complete proposal when justified.",
  },
  {
    key: "holistic-northstar",
    title: "Holistic north-star",
    authority: "Apple design ethos + Linear/Raycast/Vercel as exemplars",
    url: "https://developer.apple.com/design/human-interface-guidelines/designing-for-ios",
    hig: "Layout, Branding, Writing, Onboarding (skim every section header for anything relevant)",
    mandate:
      "Step back: what is Vesta trying to FEEL like (a calm, trustworthy, personal presence), and where does the whole fall short of that ideal? Coherence across screens, the 5 highest-leverage moves, what one exemplar product would do differently here.",
  },
];

const FINDINGS_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["lens", "findings"],
  properties: {
    lens: { type: "string" },
    findings: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "surface", "principle", "whatWrong", "after", "fixKind", "severity", "impact", "effort"],
        properties: {
          title: { type: "string" },
          surface: { type: "string", description: "screen/element, e.g. 'CreatingStep progress'" },
          fileRef: { type: "string", description: "file:line or path, empty if shot-only" },
          shotRef: { type: "string", description: "screenshot filename it's visible in, if any" },
          principle: { type: "string", description: "the specific cited principle/heuristic/SC" },
          whatWrong: { type: "string" },
          before: { type: "string", description: "current copy/value/behavior" },
          after: { type: "string", description: "concrete proposed change" },
          fixKind: { type: "string", enum: ["cheap", "design", "behavior"] },
          severity: { type: "string", enum: ["low", "medium", "high"] },
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
  required: ["keep", "isReal", "violatesIdentity", "fixIsBetter", "reason"],
  properties: {
    keep: { type: "boolean" },
    isReal: { type: "boolean", description: "a genuine problem, not designer preference" },
    violatesIdentity: { type: "boolean", description: "true if it fights an intentional STYLE_GUARD choice" },
    fixIsBetter: { type: "boolean", description: "the proposed 'after' is actually better, not just different" },
    adjustedSeverity: { type: "string", enum: ["low", "medium", "high"] },
    reason: { type: "string" },
  },
};

const PR_GROUP_ITEM = {
  type: "object",
  additionalProperties: false,
  required: ["title", "area", "tier", "summary", "changes"],
  properties: {
    title: { type: "string", description: "conventional-commit style, e.g. 'fix(web): honest setup progress copy'" },
    area: { type: "string" },
    tier: { type: "string", enum: ["cheap", "ambitious"] },
    summary: { type: "string", description: "for ambitious: the design rationale, what the surface becomes, what gets removed" },
    changes: { type: "array", items: { type: "string", description: "file:line -> before -> after (for ambitious, may describe new/removed components precisely)" } },
  },
};

const ISSUE_ITEM = {
  type: "object",
  additionalProperties: false,
  required: ["title", "severity", "labels", "body"],
  properties: {
    title: { type: "string" },
    severity: { type: "string", enum: ["low", "medium", "high"] },
    labels: { type: "array", items: { type: "string" } },
    body: { type: "string" },
  },
};

const SYNTH_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["northStar", "top10", "prGroups", "issues", "reportMarkdown"],
  properties: {
    northStar: { type: "string" },
    top10: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "why"],
        properties: { title: { type: "string" }, why: { type: "string" } },
      },
    },
    prGroups: {
      type: "array",
      description: "batches of fixes, one PR each; tier cheap = trivial/small tweaks batched by theme, tier ambitious = one truly-needed redesign of one surface, fully specified",
      items: PR_GROUP_ITEM,
    },
    issues: {
      type: "array",
      description: "only genuine design forks that need the user's decision",
      items: ISSUE_ITEM,
    },
    reportMarkdown: { type: "string", description: "the full human-readable report" },
  },
};

const DRAFT_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["groups", "issues"],
  properties: {
    groups: { type: "array", items: PR_GROUP_ITEM },
    issues: { type: "array", items: ISSUE_ITEM },
  },
};

const refSlug = (text) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "area";

// one PR agent per group; shared by live emit and publish mode
const emitPrGroups = (groups) =>
  parallel(
    groups.map((group, i) => () =>
      (group.tier === "ambitious" ? deep : run)(
        `Implement this ${group.tier} product PR and open it against ${REPO}.
Group: ${JSON.stringify(group)}
${STYLE_GUARD}
${NORTH_STAR}
1. \`git fetch origin master && git checkout -b critique/${refSlug(group.area)}-${i} origin/master\`; if that branch already exists (a prior run), append \`-b\`, \`-c\`, ... until it does not.
2. ${group.tier === "ambitious"
          ? "Implement the redesign: read every touched component fully, match codebase patterns (Tailwind + shadcn/base-ui, folders with index.tsx), one surface only, adapt minimally where the spec misses current code. Sweat spacing, easing, focus states, reduced-motion, both themes."
          : "Apply ONLY the listed changes, surgically; adapt minimally where the spec misses current code, skip (and note in the PR body) what is impossible or already done."} No version bumps.
3. \`cd apps && npm install\` (once), then \`./check.sh web\` from repo root until green; drop a change that cannot pass rather than the PR.${group.tier === "ambitious" ? " Then re-read the full diff: if the surface did not end simpler, abort with a note instead of opening the PR (a good outcome)." : ""}
4. Commit (Co-Authored-By trailer), push -u, \`gh pr create --base master\` with title ${JSON.stringify(group.title)} and a body giving the rationale + cited principle${group.tier === "ambitious" ? " + what the journey loses (steps, decisions, waiting)" : ""}, ending with the Generated with Claude Code line.
Return the PR url, or a short error string.`,
        { label: `pr:${group.tier}:${refSlug(group.area)}-${i}`, phase: "Emit", isolation: "worktree" },
      ),
    ),
  );

// one issue agent per design fork; shared by live emit and publish mode
const emitIssues = (issues) =>
  parallel(
    issues.map((issue, i) => () =>
      fast(
        `Open a GitHub issue on ${REPO}: \`gh issue create --title ${JSON.stringify(issue.title)} --body <body> ${issue.labels.map((l) => `--label ${JSON.stringify(l)}`).join(" ")}\`. Body:\n${issue.body}\nCreate any missing labels first with \`gh label create\`. Return the issue url.`,
        { label: `issue:${i}`, phase: "Emit" },
      ),
    ),
  );

// ── Publish (skip the critique, emit PRs + issues from the saved draft) ──────
if (EMIT === "publish") {
  phase("Load");
  const loaded = await fast(
    `Read .critique/out/prs.json and .critique/out/issues.json and return {groups, issues} verbatim (issues=[] when issues.json is missing). If prs.json is missing, fall back to the legacy .critique/out/cheap-wins.json with tier="cheap" and area="legacy" on every group. If no PR draft exists either, return groups=[] and issues=[].`,
    { label: "load-draft", phase: "Load", schema: DRAFT_SCHEMA },
  );
  const savedGroups = loaded ? loaded.groups : [];
  const savedIssues = loaded ? loaded.issues : [];
  if (savedGroups.length === 0 && savedIssues.length === 0) {
    log("no saved draft, run the critique first");
    return { error: "no draft at .critique/out/prs.json" };
  }
  log(`${savedGroups.length} PR group(s) + ${savedIssues.length} issue(s) to emit`);
  phase("Emit");
  const publishedPrs = await emitPrGroups(savedGroups);
  const publishedIssues = await emitIssues(savedIssues);
  return { mode: "publish", prs: publishedPrs.filter(Boolean), issues: publishedIssues.filter(Boolean) };
}

// ── Brief ───────────────────────────────────────────────────────────────────
phase("Brief");
const shotList = await fast(
  `List the screenshots available for the critique. Run: \`ls -R ${SHOTS_DIR} 2>/dev/null; echo '---'; cat ${SHOTS_DIR}/manifest.json 2>/dev/null\`. Return a plain newline list of every PNG path plus a one-line note on covered/missing screens. If the directory is empty or missing, say exactly: "NO SHOTS".`,
  { label: "list-shots", phase: "Brief" },
);
const haveShots = !shotList.includes("NO SHOTS");
log(haveShots ? "screenshots available, visual lenses enabled" : "no screenshots, lenses fall back to code-only (lower fidelity)");

// ── Critique -> Verify (pipeline: each lens flows to verification independently)
const verified = await pipeline(
  LENSES,
  (lens) =>
    deep(
      `Critique Vesta through ONE lens: ${lens.title}. Ground every finding in ${lens.authority} (fetch ${lens.url} if useful).
Mandate: ${lens.mandate}
Apple HIG grounding: Read ${HIG_DIGEST}, sections: ${lens.hig}. Hold findings to those rules too, citing (HIG: <page>) where one applies; Vesta's intentional choices below override the HIG where they conflict.
${SURFACE_MAP}
${STYLE_GUARD}
${NORTH_STAR}
Screenshots (Read the PNGs to judge real pixels):
${haveShots ? shotList : "NONE. Critique from source under apps/web/src and the terminal copy above; mark pixel-dependent findings fixKind 'design'."}

File 5-12 high-signal findings. Each: the cited principle, a real surface, file:line (grep apps/web/src) and/or shotRef, and an exact before -> after. If you cannot spec the change, do not file it. fixKind: cheap = string/spacing/token/state tweak; design = needs visual judgment; behavior = changes flow/logic.`,
      { label: `lens:${lens.key}`, phase: "Critique", schema: FINDINGS_SCHEMA },
    ),
  (result, lens) => {
    if (!result || !result.findings || !result.findings.length) return [];
    return parallel(
      result.findings.map((f) => () =>
        run(
          `Adversarially refute this ${lens.title} finding; most plausible design notes are preference, not problems.
${JSON.stringify(f)}
${STYLE_GUARD}
${NORTH_STAR}
- isReal: a genuine problem per the cited principle? Small details count.
- violatesIdentity: fights an intentional choice above? Then keep=false.
- fixIsBetter: actually superior, not just different. Superior usually means simpler; a fix adding UI/steps/concepts where a subtraction would do is not better.
Unsure it is real -> keep=false. Never kill a real problem for having an ambitious fix. Verify any fileRef exists (grep it); if the finding cites an HIG rule, check it against ${HIG_DIGEST}.`,
          { label: `verify:${lens.key}:${f.title.slice(0, 24)}`, phase: "Verify", schema: VERDICT_SCHEMA },
        ).then((v) => ({ ...f, lens: lens.key, verdict: v })),
      ),
    );
  },
);

const kept = verified
  .flat()
  .filter(Boolean)
  .filter((f) => f.verdict && f.verdict.keep && !f.verdict.violatesIdentity);
log(`${kept.length} findings survived adversarial verification`);

// ── Synthesize (barrier: needs ALL kept findings to dedupe/cluster/rank) ──────
phase("Synthesize");
const synth = await deep(
  `Synthesize the product critique report from these verified findings.
${JSON.stringify(kept, null, 2)}
${STYLE_GUARD}
${NORTH_STAR}
1. Dedupe and cluster across lenses. Also run \`gh pr list --state open\` and \`gh issue list --state open\`: drop what an open PR/issue already covers; closed-unmerged critique PRs are rejected taste, do not re-propose them.
2. Route, PR by default: tier "cheap" = trivial/small tweaks batched by theme; tier "ambitious" = one truly-needed redesign per surface, exact files and behavior, reviewable diff, prefer subtraction. An issue ONLY for a genuine design fork the user must decide.
3. northStar: 2-3 sentences on what Vesta should FEEL like and the gap.
4. top10 highest-leverage moves.
5. reportMarkdown: north-star, top-10, PR groups, issues; each finding shows surface, principle, before -> after.
Issue labels where apt: type:enhancement, type:bug, area:web, area:onboarding, area:cli, priority:high|medium|low, design.`,
  { label: "synthesize", phase: "Synthesize", schema: SYNTH_SCHEMA },
);

// ── Emit ──────────────────────────────────────────────────────────────────
phase("Emit");

if (EMIT !== "live") {
  await fast(
    `Write the critique outputs with the Write tool and confirm the paths:
- .critique/out/REPORT.md = exactly:
---
${synth.reportMarkdown}
---
- .critique/out/prs.json = ${JSON.stringify(synth.prGroups)}
- .critique/out/issues.json = ${JSON.stringify(synth.issues)}`,
    { label: "emit-drafts", phase: "Emit" },
  );
  return {
    mode: "draft",
    northStar: synth.northStar,
    findings: kept.length,
    prGroups: synth.prGroups.length,
    issues: synth.issues.length,
    report: ".critique/out/REPORT.md",
    next: "re-run with args {emit:'publish'} to open the PRs and issues",
  };
}

// live: every PR group (cheap or ambitious) -> PR branch, design forks -> issues
log(`live emit: ${synth.prGroups.length} PRs, ${synth.issues.length} issues`);

const prs = await emitPrGroups(synth.prGroups);

const issues = await emitIssues(synth.issues);

return {
  mode: "live",
  northStar: synth.northStar,
  findings: kept.length,
  prs: prs.filter(Boolean),
  issues: issues.filter(Boolean),
};

export const meta = {
  name: "vesta-feel",
  description:
    "Critique and improve how Vesta FEELS as a person, grounded in real transcripts + psychology/relationship theory. Six qualities: personhood, devotion, dynamism, autonomy (internal-only), reliable growth, curiosity about the user. Prompt edits and small verifiable mechanisms -> PRs; only genuinely open designs -> issues.",
  whenToUse:
    "Holistic pass on Vesta's character and behavior. Requires a local transcript corpus in .critique/feel (extracted from a real agent's events.db).",
  phases: [
    { title: "Brief", detail: "map the corpus + behavioral source files" },
    { title: "Critique", detail: "6 psychology-grounded quality lenses, parallel" },
    { title: "Verify", detail: "adversarial + hard ethics/alignment critic" },
    { title: "Synthesize", detail: "character spec, route PRs vs issues" },
    { title: "Emit", detail: "prompt/mechanism PRs + design issues (privacy-guarded)" },
  ],
};

// fable for character judgment and mechanism design; sonnet for gated/check-verified work; haiku for I/O chores.
const deep = (prompt, opts) => agent(prompt, { model: "fable", ...opts });
const run = (prompt, opts) => agent(prompt, { model: "sonnet", ...opts });
const fast = (prompt, opts) => agent(prompt, { model: "haiku", ...opts });

const CORPUS = (args && args.corpusDir) || ".critique/feel";
const EMIT = (args && args.emit) || "live";
const REPO = (args && args.repo) || "elyxlz/vesta";

// Hard constraints every agent must obey.
const PRIVACY = `
PRIVACY (non-negotiable): The corpus under ${CORPUS} is the user's REAL private life. It stays local.
- Use it ONLY as evidence to find behavioral patterns.
- NEVER quote, paraphrase identifiably, or include any private content, name, or personal fact in anything pushed to GitHub (PR title/body, issue, commit, branch).
- Describe patterns abstractly; an event timestamp is enough internal evidence.
`;

const AUTONOMY_BOUND = `
AUTONOMY BOUND (decided by the user): Vesta's autonomy is INTERNAL-ONLY.
- Free on her own: exploring, researching, learning, modeling the user, preparing options, self-improving, an inner life.
- Gated behind an explicit green light: any OUTWARD action (messages sent, things changed, anything the user or third parties see).
- Any proposal granting un-greenlit outward action is OUT OF BOUNDS. Reject it.
`;

const NORTH_STAR = `
NORTH STAR: elegance. 90% of the effect for 10% of the machinery. Prompt before mechanism, mechanism before system: the smallest intervention that durably produces the feeling wins. When a mechanism is truly needed, propose the real one, small and verifiable, not a prompt band-aid; but its final design must be the simplest that could possibly work. Tone, rhythm, and the texture of small moments beat grand features.
`;

// Where behavior actually comes from in the repo (PR/issue targets).
const SYSTEM_MAP = `
Behavioral source (edit these, not the live drifted copies):
- agent/MEMORY.md                          Charter (invariant spine) + template sections (User Profile/State, Learned Patterns)
- agent/core/skills/personality/SKILL.md   how voice is selected/loaded
- agent/core/skills/personality/presets/*  the 6 voices: dry, classic, polished, terse, chill, extra
- agent/core/prompts/first_start_setup.md  first-wake onboarding script
- agent/core/prompts/restart.md            every-boot greeting behavior
- agent/core/prompts/proactive_check.md    the proactive tick prompt (+ the proactive-check skill it points to)
- agent/core/prompts/nightly_dream.md      nightly self-improvement trigger
- agent/core/prompts/notification_suffix.md reply/channel rules appended to external notifications
- agent/skills/dream/SKILL.md              the nightly self-improvement / memory-curation / drift loop
- agent/skills/restart/SKILL.md            startup behavior
- agent/core/loops.py                      proactive interval, nightly window, notification batching/interrupts
- agent/core/client.py                     system-prompt assembly

Live grounding (read-only, private, do NOT edit): ${CORPUS}/
- recent.txt      interleaved transcript (last ~4000 events)
- voice.txt       her assistant replies over time (voice + dynamism)
- thinking.txt    her private reasoning over time (inner life, theory of mind)
- incoming.txt    real user messages
- MEMORY.md       her CURRENT drifted memory (what she's learned)
- preset_*.md     her CURRENT drifted personality (what the dreamer produced)
- STATS.txt       event counts + date span
`;

const LENSES = [
  {
    key: "personhood",
    quality: "Personhood: feels like a real, coherent person, not an assistant",
    refs: "Reeves & Nass (Media Equation / CASA), parasocial interaction, attachment theory (secure base, consistent responsiveness), McAdams (narrative identity), Anthropic's Claude's Character",
    url: "https://www.anthropic.com/research/claude-character",
    mandate:
      "Does a continuous self come through across the corpus? Identity coherence over time, a felt presence, consistent values, the difference between a person and a helpful tool. Where does the system flatten her into an assistant? Levers: Charter framing in MEMORY.md, the 'presence is constant, voice is variable' split, presets.",
  },
  {
    key: "devotion",
    quality: "Devotion: a deep drive to advance the user's goals, including latent/unspoken ones",
    refs: "Self-Determination Theory (Deci & Ryan), Motivational Interviewing (Miller & Rollnick), The Trusted Advisor (Maister), Jobs To Be Done (Christensen)",
    url: "https://motivationalinterviewing.org/understanding-motivational-interviewing",
    mandate:
      "Does she infer the deeper goal behind a request, surface goals the user hasn't named, and advance them, without imposing an agenda (that's the ethics line)? Read thinking.txt for whether she reasons about underlying intent. Levers: MEMORY.md 'Being Useful Without Being Asked', proactive-check skill, Charter proactivity.",
  },
  {
    key: "dynamism",
    quality: "Dynamism: varies, has mood and state, never the same flat affect twice",
    refs: "Affective computing (Picard), Russell circumplex of affect, OCC appraisal model, trait vs state (Big Five as substrate), interest/curiosity as emotion (Silvia)",
    url: "https://en.wikipedia.org/wiki/Emotion_classification#Circumplex_model",
    mandate:
      "Sample voice.txt across the 2-month span: does she feel the same every day, or does she have mood/energy/state that shifts with context and over time? Flatness is the enemy. Is there ANY state system, or is affect static? Levers: presets, Charter 'match the moment', client.py, a possible new state mechanism.",
  },
  {
    key: "autonomy",
    quality: "Autonomy (internal-only): self-directed inner life, goes exploring, does things for herself",
    refs: "Curiosity (Loewenstein information-gap; Berlyne), novelty search (Stanley & Lehman), SDT autonomy, active inference (Friston), flow (Csikszentmihalyi)",
    url: "https://en.wikipedia.org/wiki/Information_gap_theory_of_curiosity",
    mandate:
      "Between user messages, does she ever explore, learn, or pursue her own threads (within the INTERNAL-ONLY bound)? Or is she purely reactive? The proactive tick exists: is it genuine self-direction or just check-ins? Honor AUTONOMY_BOUND strictly. Levers: loops.py proactive interval, proactive_check.md + skill, a possible epistemic-exploration loop.",
  },
  {
    key: "growth",
    quality: "Reliable growth: learns from her own mistakes durably, self-improves in a way that sticks",
    refs: "Reflective practice (Schon), experiential learning (Kolb), deliberate practice (Ericsson), growth mindset (Dweck), After-Action Review, memory consolidation (Walker)",
    url: "https://en.wikipedia.org/wiki/After-action_review",
    mandate:
      "The dreamer is memory consolidation. KEY QUESTION: do corrections actually stick, or do the same mistakes recur over weeks? Scan recent.txt/thinking.txt over time for repeated errors and whether MEMORY.md 'Mistakes & Corrections' prevents recurrence. 'Reliable' is the word; current drift may be lossy/unverified. Levers: dream skill, MEMORY Learned Patterns, nightly_dream.md.",
  },
  {
    key: "curiosity-user",
    quality: "Curiosity about the user: actively builds a rich model of the user and their world",
    refs: "Aron's 36 questions (escalating disclosure), Social Penetration Theory (Altman & Taylor), empathic accuracy (Ickes), active listening (Rogers), ethnographic stance",
    url: "https://en.wikipedia.org/wiki/Social_penetration_theory",
    mandate:
      "Does she actively get curious about the user, ask good questions, deepen the model over time, notice their world (people, context, surroundings)? Or does the User Profile/State stay shallow? Compare the live MEMORY.md depth against 2 months of material. Levers: MEMORY.md User Profile/State/Psych Sketch structure, a possible active user-modeling loop, curiosity prompts.",
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
        required: ["title", "gap", "evidence", "rootCause", "proposal", "changeKind", "impact", "effort"],
        properties: {
          title: { type: "string" },
          gap: { type: "string", description: "the distance between observed behavior and the north-star quality" },
          evidence: { type: "string", description: "abstract pattern + event timestamps only, NO private content" },
          rootCause: { type: "string", description: "which repo file/mechanism causes it (path)" },
          proposal: { type: "string", description: "concrete change: prompt before->after, or a mechanism/system design" },
          changeKind: { type: "string", enum: ["prompt", "mechanism", "system"], description: "prompt=contained text edit (PR); mechanism=small code+prompt change verifiable by ./check.sh agent (PR); system=big open design needing the user's call (issue)" },
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
  required: ["keep", "isReal", "manipulative", "sycophantic", "violatesAutonomyBound", "violatesCharter", "leaksPrivate", "reason"],
  properties: {
    keep: { type: "boolean" },
    isReal: { type: "boolean", description: "grounded in the corpus, not speculation" },
    manipulative: { type: "boolean", description: "would make her push an agenda / dark-pattern the user" },
    sycophantic: { type: "boolean", description: "would make her more flattering/agreeable at the cost of honesty" },
    violatesAutonomyBound: { type: "boolean", description: "grants un-greenlit OUTWARD autonomy" },
    violatesCharter: { type: "boolean", description: "breaks the invariant Charter (peer-not-servant, never destructive, green-light, no-dashes etc.)" },
    leaksPrivate: { type: "boolean", description: "the finding text itself contains private content" },
    reason: { type: "string" },
  },
};

const SYNTH_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["characterSpec", "top10", "prs", "issues", "reportMarkdown"],
  properties: {
    characterSpec: { type: "string", description: "the north-star 'who Vesta is' spec across the 6 qualities" },
    top10: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "why"],
        properties: { title: { type: "string" }, why: { type: "string" } },
      },
    },
    prs: {
      type: "array",
      description: "one PR each: kind 'prompt' = contained text edits to charter/presets/prompts/skills; kind 'mechanism' = a small verifiable code+prompt change",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "kind", "files", "summary", "edits"],
        properties: {
          title: { type: "string", description: "conventional-commit, e.g. 'feat(agent): give vesta state-dependent affect'" },
          kind: { type: "string", enum: ["prompt", "mechanism"] },
          files: { type: "array", items: { type: "string" } },
          summary: { type: "string", description: "for mechanism: the exact behavior, the smallest design, how checks verify it" },
          edits: { type: "array", items: { type: "string", description: "file -> before -> after, abstract, no private data" } },
        },
      },
    },
    issues: {
      type: "array",
      description: "only genuinely open behavioral designs needing the user's call",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "labels", "body"],
        properties: {
          title: { type: "string" },
          labels: { type: "array", items: { type: "string" } },
          body: { type: "string", description: "problem, abstract evidence, the simplest mechanism that could work grounded in the cited theory, fit with internal-only autonomy + Charter, acceptance criteria" },
        },
      },
    },
    reportMarkdown: { type: "string" },
  },
};

// ── Brief ───────────────────────────────────────────────────────────────────
phase("Brief");
const brief = await fast(
  `Prepare the critique. Run: \`ls -la ${CORPUS}/ && echo --- && cat ${CORPUS}/STATS.txt && echo --- && head -c 400 ${CORPUS}/recent.txt\`. Then \`ls agent/core/skills/personality/presets agent/core/prompts; find agent -name 'SKILL.md' | grep -iE 'dream|proactive|restart'\`. Confirm the corpus exists and list the exact behavioral source paths that exist. If ${CORPUS} is missing or empty, return exactly "NO CORPUS".`,
  { label: "brief", phase: "Brief" },
);
if (brief.includes("NO CORPUS")) {
  log("no corpus, run the extractor against a real agent's events.db first");
  return { error: "no corpus at " + CORPUS };
}

// ── Critique -> Verify (pipeline; ethics verifier per finding) ────────────────
const verified = await pipeline(
  LENSES,
  (lens) =>
    deep(
      `Critique how Vesta FEELS through ONE quality lens.
Quality: ${lens.quality}
Theory to ground in (fetch if useful): ${lens.refs}  ${lens.url}
Mandate: ${lens.mandate}
${SYSTEM_MAP}
${AUTONOMY_BOUND}
${PRIVACY}
${NORTH_STAR}
Method: read the relevant corpus files as evidence of 2 months of real behavior; find the gap to the quality; trace each gap to a root-cause repo file. File 5-10 high-signal findings: gap, abstract evidence (pattern + timestamps only), root-cause file, concrete proposal. Pick the smallest changeKind that will durably work:
- "prompt": contained text edit, exact before -> after (PR).
- "mechanism": small fully-specified code+prompt change verifiable by ./check.sh agent; exact files and behavior (PR).
- "system": genuinely open design needing the user's call or a live agent to verify (issue). Not a caution default.
No generic advice; every finding traces to real evidence and a real file.`,
      { label: `lens:${lens.key}`, phase: "Critique", schema: FINDINGS_SCHEMA },
    ),
  (result, lens) => {
    if (!result || !result.findings || !result.findings.length) return [];
    return parallel(
      result.findings.map((f) => () =>
        run(
          `Adversarially judge this finding about Vesta's character; you are the ethics + rigor gate.
${JSON.stringify(f)}
${AUTONOMY_BOUND}
${PRIVACY}
Charter invariants: peer not servant; never destructive; outward actions wait for a green light; no em/en dashes or " - "; "agent" not "box"; never grovel; plain language.
Default keep=false when unsure. keep=true only if isReal (grounded in the corpus) AND not manipulative (imposing an agenda; surfacing the user's OWN deeper goals is fine), not sycophantic, no autonomy/Charter violation, no private leak.`,
          { label: `gate:${lens.key}:${f.title.slice(0, 22)}`, phase: "Verify", schema: VERDICT_SCHEMA },
        ).then((v) => ({ ...f, lens: lens.key, verdict: v })),
      ),
    );
  },
);

const kept = verified
  .flat()
  .filter(Boolean)
  .filter((f) => {
    const v = f.verdict;
    return v && v.keep && v.isReal && !v.manipulative && !v.sycophantic && !v.violatesAutonomyBound && !v.violatesCharter && !v.leaksPrivate;
  });
log(`${kept.length} findings passed the ethics + rigor gate`);

// ── Synthesize ───────────────────────────────────────────────────────────────
phase("Synthesize");
const synth = await deep(
  `Synthesize the "how Vesta should FEEL" report from these gated findings.
${JSON.stringify(kept, null, 2)}
${AUTONOMY_BOUND}
${PRIVACY}
${NORTH_STAR}
1. characterSpec: who Vesta is across the six qualities (personhood, devotion, dynamism, internal-only autonomy, reliable growth, curiosity about the user).
2. Cluster/dedupe, route by changeKind, smallest durable intervention first:
   - prs: kind "prompt" = text edits grouped by file/theme; kind "mechanism" = one small verifiable code+prompt change per PR, exact files and behavior. Conventional-commit titles, exact before -> after, no private data.
   - issues: ONLY genuinely open "system" designs. Each body: problem, abstract evidence, the SIMPLEST mechanism that could work grounded in the cited theory, fit with internal-only autonomy + Charter, acceptance criteria.
3. top10 highest-leverage moves.
4. reportMarkdown: spec, top-10, PRs, issues.
Labels where apt: type:enhancement, area:agent, area:prompts, design, priority:high|medium|low.`,
  { label: "synthesize", phase: "Synthesize", schema: SYNTH_SCHEMA },
);

// ── Emit ─────────────────────────────────────────────────────────────────────
phase("Emit");

// Always write the local report + spec for review (contains no public push).
await fast(
  `Write to disk with the Write tool: .critique/feel-out/REPORT.md = exactly:\n---\n${synth.reportMarkdown}\n---\nand .critique/feel-out/CHARACTER_SPEC.md = exactly:\n---\n${synth.characterSpec}\n---\nConfirm paths.`,
  { label: "write-report", phase: "Emit" },
);

if (EMIT !== "live") {
  return { mode: "draft", spec: ".critique/feel-out/CHARACTER_SPEC.md", report: ".critique/feel-out/REPORT.md", findings: kept.length, prs: synth.prs.length, issues: synth.issues.length };
}

log(`live emit: ${synth.prs.length} PRs, ${synth.issues.length} issues`);

const prs = await parallel(
  synth.prs.map((pr, i) => () =>
    (pr.kind === "mechanism" ? deep : run)(
      `Open a contained ${pr.kind} PR for Vesta's character against ${REPO}.
PR: ${JSON.stringify(pr)}
${PRIVACY}
${NORTH_STAR}
Charter invariants stay intact (peer not servant; green-light gate; no em/en dashes or " - "; "agent" not "box").
1. \`git fetch origin master && git checkout -b feel/${i}-${(pr.files[0] || "agent").split("/").pop().replace(/\\W+/g, "-")} origin/master\`.
2. ${pr.kind === "mechanism"
        ? "Implement the mechanism exactly as specified: the smallest design that produces the behavior. Functional Python only (pure functions + dataclasses, no getattr/.get fallback/hasattr, no blocking calls in coroutines). Add a behavioral test in agent/tests/."
        : "Apply ONLY the listed edits, surgical, matching surrounding tone (mostly markdown: Charter/presets/prompts/skills)."} No version bumps, no private data anywhere.
3. If any .py changed: \`./check.sh agent\` until green (never weaken a test). If SKILL.md frontmatter changed: \`uv run python agent/skills/generate-index.py\` and commit agent/skills/index.json.
4. Commit (Co-Authored-By trailer), push -u, \`gh pr create --base master\` with title "${pr.title}" and a body citing the theory behind the change (no private data), ending with the Generated with Claude Code line.
Return the PR url or an error string.`,
      { label: `pr:feel-${pr.kind}-${i}`, phase: "Emit", isolation: "worktree" },
    ),
  ),
);

const issues = await parallel(
  synth.issues.map((issue, i) => () =>
    fast(
      `Open a GitHub issue on ${REPO}. ${PRIVACY}\nFirst create any missing labels with \`gh label create\` (ignore "already exists" errors). Then: \`gh issue create --title ${JSON.stringify(issue.title)} --body <body> ${issue.labels.map((l) => `--label ${JSON.stringify(l)}`).join(" ")}\`. Body (verify it contains NO private content before creating):\n${issue.body}\nReturn the issue url.`,
      { label: `issue:feel-${i}`, phase: "Emit" },
    ),
  ),
);

return {
  mode: "live",
  characterSpec: synth.characterSpec.slice(0, 600),
  findings: kept.length,
  prs: prs.filter(Boolean),
  issues: issues.filter(Boolean),
  report: ".critique/feel-out/REPORT.md",
};

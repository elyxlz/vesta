export const meta = {
  name: "product-emit",
  description: "Emit the product-critique PRs from the saved draft (.critique/out/prs.json): cheap wins and ambitious redesigns, one PR per group, branched off master with web checks.",
  phases: [
    { title: "Load", detail: "read the saved PR groups" },
    { title: "Emit", detail: "one worktree PR agent per group" },
  ],
};

// fable only for ambitious redesigns; sonnet for check-verified cheap wins; haiku to load the draft.
const deep = (prompt, opts) => agent(prompt, { model: "fable", ...opts });
const run = (prompt, opts) => agent(prompt, { model: "sonnet", ...opts });
const fast = (prompt, opts) => agent(prompt, { model: "haiku", ...opts });

const REPO = (args && args.repo) || "elyxlz/vesta";

const GROUPS_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["groups"],
  properties: {
    groups: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "area", "tier", "summary", "changes"],
        properties: {
          title: { type: "string" },
          area: { type: "string" },
          tier: { type: "string", enum: ["cheap", "ambitious"] },
          summary: { type: "string" },
          changes: { type: "array", items: { type: "string" } },
        },
      },
    },
  },
};

phase("Load");
const loaded = await fast(
  `Read .critique/out/prs.json and return its PR groups verbatim. If missing, fall back to the legacy .critique/out/cheap-wins.json with tier="cheap" on every group. If neither exists, return groups=[].`,
  { label: "load-draft", phase: "Load", schema: GROUPS_SCHEMA },
);
const groups = loaded ? loaded.groups : [];
if (groups.length === 0) {
  log("no saved draft, run product-critique first");
  return { error: "no PR groups at .critique/out/prs.json" };
}
log(`${groups.length} PR group(s) to emit`);

phase("Emit");
const prs = await parallel(
  groups.map((group, i) => () =>
    (group.tier === "ambitious" ? deep : run)(
      `Open ONE ${group.tier} product PR against ${REPO} from the product-critique draft.
Group: ${JSON.stringify(group)}
NORTH STAR: elegance, 90% of the value for 10% of the effort; the surface must end simpler, not busier; sweat the details.
Intentional, never "fix": all-lowercase UI copy, no em/en dashes or " - " separators (commas/colons), "agent" never "box".
1. \`git fetch origin master && git checkout -b critique/${i}-emit origin/master\`.
2. ${group.tier === "ambitious"
        ? "Implement the redesign in summary + changes: read every touched component fully, match codebase patterns (Tailwind + shadcn/base-ui, folders with index.tsx), one surface only, adapt minimally where the spec misses current code. Sweat spacing, easing, focus states, reduced-motion, both themes."
        : "Apply ONLY the listed changes, surgically; adapt minimally where the spec misses current code, skip (and note in the PR body) what is impossible or already done."} No version bumps.
3. \`cd apps && npm install\` (once), then \`./check.sh web\` from repo root until green; drop a change that cannot pass rather than the PR.${group.tier === "ambitious" ? " Then re-read the full diff: if the surface did not end simpler, abort with a note instead of opening the PR (a good outcome)." : ""}
4. Commit (Co-Authored-By trailer), \`git push -u origin\`, \`gh pr create --base master --title ${JSON.stringify(group.title)}\` with a body giving the rationale + cited principle${group.tier === "ambitious" ? " + what the journey loses (steps, decisions, waiting)" : ""}, ending with: 🤖 Generated with [Claude Code](https://claude.com/claude-code)
Return the PR url, or a short error string.`,
      { label: `pr:${group.tier}:${i}`, phase: "Emit", isolation: "worktree" },
    ),
  ),
);

return { prs: prs.filter(Boolean) };

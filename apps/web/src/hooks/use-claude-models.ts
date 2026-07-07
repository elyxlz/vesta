import { useManifest } from "@/hooks/use-manifest";
import type { OpenRouterModelOption } from "@/api/providers/openrouter";

// Display label + one-word strength note per Claude slug, so the picker can say what each is for
// (opus is the strongest, sonnet is faster) instead of showing a bare lowercase slug.
const CLAUDE_MODEL_META: Record<string, { label: string; note: string }> = {
  opus: { label: "Claude Opus", note: "strongest" },
  sonnet: { label: "Claude Sonnet", note: "faster, lighter" },
};

function claudeOption(slug: string): OpenRouterModelOption {
  const meta = CLAUDE_MODEL_META[slug];
  return {
    slug,
    label: meta ? meta.label : slug,
    author: "Anthropic",
    note: meta?.note,
  };
}

// Shown immediately; refined from the manifest (GET /manifest) so a newly added model appears
// without a code change. claude-code resolves the aliases.
const CLAUDE_FALLBACK: OpenRouterModelOption[] = ["opus", "sonnet"].map(
  claudeOption,
);

/// The Claude model list as model-card options for the provider card's model switcher, derived from
/// the manifest's Claude catalog. Starts from the static fallback until the manifest resolves.
/// `enabled` is kept for call-site symmetry with the OpenRouter path.
export function useClaudeModels(enabled = true): OpenRouterModelOption[] {
  const manifest = useManifest();
  if (!enabled) return CLAUDE_FALLBACK;
  const models = manifest?.providers["claude"]?.models;
  if (!Array.isArray(models) || models.length === 0) return CLAUDE_FALLBACK;
  return models.map(claudeOption);
}

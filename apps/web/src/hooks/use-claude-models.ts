import { useManifest } from "@/hooks/use-manifest";
import type { OpenRouterModelOption } from "@/api/providers/openrouter";

// One-word strength note per Claude slug; display labels come from the provider
// manifest, with the fallback below keeping older gateways readable.
const CLAUDE_MODEL_NOTES: Record<string, string> = {
  opus: "strongest",
  sonnet: "faster, lighter",
};

function claudeOption(slug: string, label?: string): OpenRouterModelOption {
  return {
    slug,
    label: label ?? slug,
    author: "Anthropic",
    note: CLAUDE_MODEL_NOTES[slug],
  };
}

// Shown immediately; refined from the manifest (GET /manifest) so a newly added model appears
// without a code change. claude-code resolves the aliases.
const CLAUDE_FALLBACK: OpenRouterModelOption[] = ["opus", "sonnet"].map(
  (slug) =>
    claudeOption(slug, `${slug[0]?.toUpperCase() ?? ""}${slug.slice(1)}`),
);

/// The Claude model list as model-card options for the provider card's model switcher, derived from
/// the manifest's Claude catalog. Starts from the static fallback until the manifest resolves.
/// `enabled` is kept for call-site symmetry with the OpenRouter path.
export function useClaudeModels(enabled = true): OpenRouterModelOption[] {
  const manifest = useManifest();
  if (!enabled) return CLAUDE_FALLBACK;
  const entry = manifest?.providers.claude;
  const models = entry?.models;
  const names = entry?.model_names;
  if (!Array.isArray(models) || models.length === 0) return CLAUDE_FALLBACK;
  return models.map((slug) => claudeOption(slug, names?.[slug]));
}

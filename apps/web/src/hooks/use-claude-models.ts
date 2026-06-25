import { useManifest } from "@/hooks/use-manifest";
import type { OpenRouterModelOption } from "@/api/providers/openrouter";

// Shown immediately; refined from the manifest (GET /manifest) so a newly added model appears
// without a code change. claude-code resolves the aliases.
const CLAUDE_FALLBACK: OpenRouterModelOption[] = [
  { slug: "opus", label: "Claude Opus", author: "Anthropic" },
  { slug: "sonnet", label: "Claude Sonnet", author: "Anthropic" },
  { slug: "haiku", label: "Claude Haiku", author: "Anthropic" },
];

/// The Claude model list as model-card options for the provider card's model switcher, derived from
/// the manifest's Claude catalog. Starts from the static fallback until the manifest resolves.
/// `enabled` is kept for call-site symmetry with the OpenRouter path.
export function useClaudeModels(enabled = true): OpenRouterModelOption[] {
  const manifest = useManifest();
  if (!enabled) return CLAUDE_FALLBACK;
  const models = manifest?.providers["claude"]?.models;
  if (!Array.isArray(models) || models.length === 0) return CLAUDE_FALLBACK;
  return models.map((slug) => ({ slug, label: slug, author: "Anthropic" }));
}

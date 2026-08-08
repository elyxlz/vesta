import type { Manifest } from "@/api/manifest";
import type { OpenRouterModelOption } from "@/api/providers/openrouter";
import type { ProviderMode } from "./types";

/// The two Claude aliases every picker offers as primary buttons ahead of the
/// expandable live-slug list. Shared by onboarding (ProviderPicker) and the
/// settings model switcher (ProviderCard) so the pair never drifts apart.
export const CLAUDE_ALIASES: OpenRouterModelOption[] = [
  { slug: "opus", label: "Opus", author: "Anthropic" },
  { slug: "sonnet", label: "Sonnet", author: "Anthropic" },
];

/** Build the fixed-model picker options from the manifest; OpenRouter owns a live catalog. */
export function providerModelOptions(
  provider: ProviderMode | null,
  manifest: Manifest | undefined,
  claudeModels: OpenRouterModelOption[],
  currentModel?: string | null,
): OpenRouterModelOption[] | undefined {
  if (provider === "claude") return claudeModels;
  if (provider === null || provider === "openrouter") return undefined;

  const entry = manifest?.providers[provider];
  const models = Array.isArray(entry?.models)
    ? entry.models
    : currentModel
      ? [currentModel]
      : [];
  if (models.length === 0) return undefined;
  return models.map((slug) => ({
    slug,
    label: entry?.model_names?.[slug] ?? slug,
    author: entry?.display ?? provider,
  }));
}

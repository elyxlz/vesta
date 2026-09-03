import { CLAUDE_ALIASES as CORE_CLAUDE_ALIASES } from "@vesta/core";
import type {
  ProviderKind,
  OpenRouterModelOption,
  ProviderCatalog,
} from "@vesta/core";

/// The two Claude aliases every picker offers as primary buttons ahead of the
/// expandable live-slug list, owned by @vesta/core so web and mobile never drift.
export const CLAUDE_ALIASES: OpenRouterModelOption[] = CORE_CLAUDE_ALIASES.map(
  (alias) => ({ ...alias, author: "Anthropic" }),
);

/** Build fixed-model picker options from the provider catalog. Live providers
 * (OpenRouter, Claude) return undefined: they feed the picker their own way. */
export function providerModelOptions(
  provider: ProviderKind | null,
  catalog: ProviderCatalog | undefined,
  currentModel?: string | null,
): OpenRouterModelOption[] | undefined {
  if (provider === null || provider === "openrouter" || provider === "claude")
    return undefined;

  const entry = catalog?.providers[provider];
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

import type { Manifest } from "@/api/manifest";
import type { OpenRouterModelOption } from "@/api/providers/openrouter";
import type { ProviderMode } from "./types";

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
    label: slug.toUpperCase(),
    author: entry?.display ?? provider,
  }));
}

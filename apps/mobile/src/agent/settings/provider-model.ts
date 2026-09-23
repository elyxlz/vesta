import { CLAUDE_ALIASES, contextForModel } from "@vesta/core";
import type {
  ProviderCatalogEntry,
  ProviderContextPolicy,
  ProviderKind,
} from "@vesta/core";

export interface ModelOption {
  label: string;
  value: string;
}

export interface LiveModel {
  slug: string;
  label: string;
}

// The two Claude aliases offered ahead of the live catalog (owned by @vesta/core), so the
// picker still shows something useful when the live fetch fails or has not resolved yet.
export const CLAUDE_ALIAS_OPTIONS: ModelOption[] = CLAUDE_ALIASES.map(
  (alias) => ({
    label: alias.label,
    value: alias.slug,
  }),
);

export function sortAdvertisedProviders(
  providers: Partial<Record<ProviderKind, ProviderCatalogEntry>>,
): ProviderKind[] {
  return (Object.keys(providers) as ProviderKind[]).sort(
    (left, right) =>
      (providers[left]?.order ?? Number.MAX_SAFE_INTEGER) -
      (providers[right]?.order ?? Number.MAX_SAFE_INTEGER),
  );
}

function toOption(model: LiveModel): ModelOption {
  return { label: model.label, value: model.slug };
}

export function buildModelOptions(
  providerKind: ProviderKind,
  entry: ProviderCatalogEntry | undefined,
  openRouterModels: readonly LiveModel[] | undefined,
  claudeModels: readonly LiveModel[] | undefined,
): ModelOption[] {
  if (providerKind === "openrouter") {
    return (openRouterModels ?? []).map(toOption);
  }
  if (providerKind === "claude") return (claudeModels ?? []).map(toOption);
  if (!entry || !Array.isArray(entry.models)) return [];
  return entry.models.map((model) => ({
    label: entry.model_names?.[model] ?? model,
    value: model,
  }));
}

// The context windows a model offers, or null when there is nothing to choose: OpenRouter models
// carry their own limit, and a policy with no presets has one fixed window.
export function contextPolicyToOffer(
  providerKind: ProviderKind,
  entry: ProviderCatalogEntry | undefined,
  model: string,
): ProviderContextPolicy | null {
  if (providerKind === "openrouter") return null;
  const policy = contextForModel(entry, model);
  return policy && policy.presets.length > 0 ? policy : null;
}

// A window as the user reads it: the preset's own label when one matches, else thousands.
export function contextLabel(
  tokens: number,
  policy: ProviderContextPolicy,
): string {
  const preset = policy.presets.find((option) => option.tokens === tokens);
  if (preset) return preset.label;
  return tokens >= 1_000_000
    ? `${String(tokens / 1_000_000)}M`
    : `${String(Math.round(tokens / 1000))}K`;
}

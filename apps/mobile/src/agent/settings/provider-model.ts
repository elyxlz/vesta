import { CLAUDE_ALIASES } from "@vesta/core";
import type { ProviderKind, ProviderManifestEntry } from "@vesta/core";

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
const CLAUDE_ALIAS_OPTIONS: ModelOption[] = CLAUDE_ALIASES.map(
  (alias) => ({
    label: alias.label,
    value: alias.slug,
  }),
);

// Before sign-in the wire reports "none", so the section works off the kind the
// user picked in the connect card; once signed in the wire's kind wins.
export function resolveProviderKind(
  signedInKind: ProviderKind | "none",
  authKind: ProviderKind,
): ProviderKind {
  return signedInKind === "none" ? authKind : signedInKind;
}

export function sortAdvertisedProviders(
  providers: Partial<Record<ProviderKind, ProviderManifestEntry>>,
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
  entry: ProviderManifestEntry | undefined,
  openRouterModels: readonly LiveModel[] | undefined,
  claudeModels: readonly LiveModel[] | undefined,
): ModelOption[] {
  if (providerKind === "openrouter") {
    return (openRouterModels ?? []).map(toOption);
  }
  if (providerKind === "claude") {
    return [...CLAUDE_ALIAS_OPTIONS, ...(claudeModels ?? []).map(toOption)];
  }
  if (!entry || !Array.isArray(entry.models)) return [];
  return entry.models.map((model) => ({
    label: entry.model_names?.[model] ?? model,
    value: model,
  }));
}

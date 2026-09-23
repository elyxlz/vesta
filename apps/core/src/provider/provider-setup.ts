import type {
  ProviderCatalog,
  ProviderContextPolicy,
  ProviderContextPreset,
  ProviderKind,
  ProviderSelection,
} from "./provider";

// The Claude plan tier drives which context windows the picker offers: the 1M-context beta is a
// Max-only entitlement, so a Pro/Free agent that selects a >200K window would send an unentitled
// beta header and fail on its first turn. We gate the presets and default off the plan instead.

// The plan tier from a raw `.credentials.json` OAuth blob, or null when absent/unparseable. During
// onboarding the blob is only ever client-side (agent-scoped OAuth, not yet installed), so the
// wizard reads the plan straight from it; the settings screen gets the plan from GET /provider.
export function planFromCredentials(credentials: string): string | null {
  try {
    const parsed: unknown = JSON.parse(credentials);
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      "claudeAiOauth" in parsed
    ) {
      const oauth = parsed.claudeAiOauth;
      if (
        oauth !== null &&
        typeof oauth === "object" &&
        "subscriptionType" in oauth
      ) {
        const plan = oauth.subscriptionType;
        return typeof plan === "string" ? plan : null;
      }
    }
  } catch {
    return null;
  }
  return null;
}

// A preset is offered when it carries no plan restriction, or the known plan is in its allowlist. A
// null plan (unknown tier) is permissive: we only hide a window when we know the plan can't use it.
function presetAllowed(
  preset: ProviderContextPreset,
  plan: string | null,
): boolean {
  return (
    preset.plans === undefined || plan === null || preset.plans.includes(plan)
  );
}

// The presets to offer and the initial selection for a context step, given the known plan (or null).
export function planContextOptions(
  context: ProviderContextPolicy,
  plan: string | null,
): { presets: ProviderContextPreset[]; initial: number } {
  const presets = context.presets.filter((preset) =>
    presetAllowed(preset, plan),
  );
  const preferred =
    plan === null ? undefined : context.defaults_by_plan?.[plan];
  const inPresets = (tokens: number) =>
    presets.some((preset) => preset.tokens === tokens);
  const initial =
    preferred !== undefined && inPresets(preferred)
      ? preferred
      : inPresets(context.default)
        ? context.default
        : (presets[presets.length - 1]?.tokens ?? context.default);
  return { presets, initial };
}

// The setup flow's final selection, or null while an OAuth provider has no credentials yet.
// A zero context means "the provider's own default" and is left off the wire.
export function providerResult(
  provider: ProviderKind,
  credentials: string | null,
  key: string,
  model: string,
  maxContextTokens: number,
): ProviderSelection | null {
  if (provider === "claude") {
    return credentials === null
      ? null
      : {
          kind: "claude",
          credentials,
          model: model || undefined,
          maxContextTokens,
        };
  }
  if (provider === "openai") {
    return credentials === null
      ? null
      : {
          kind: "openai",
          credentials,
          model,
          ...(maxContextTokens > 0 ? { maxContextTokens } : {}),
        };
  }
  return {
    kind: provider,
    key,
    model,
    ...(maxContextTokens > 0 ? { maxContextTokens } : {}),
  };
}

// The initial model-step selection: the in-progress choice wins, else Claude
// defaults to the "opus-latest" alias, else the catalog's per-provider default.
export function modelStepInitialModel(
  provider: ProviderKind | null,
  model: string,
  catalog: ProviderCatalog,
): string {
  if (model) return model;
  if (provider === "claude") return "opus-latest";
  if (provider === null) return "";
  return catalog.providers[provider]?.default_model ?? "";
}

export function providerUsesOAuth(
  provider: ProviderKind | null,
  catalog: ProviderCatalog,
): boolean {
  if (provider === null) return false;
  const authKind = catalog.providers[provider]?.auth_kind;
  return authKind === "claude_oauth" || authKind === "device_oauth";
}

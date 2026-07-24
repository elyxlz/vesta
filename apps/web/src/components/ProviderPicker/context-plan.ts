import type { ContextPreset, ProviderContext } from "@/api/manifest";

// The Claude plan tier drives which context windows the picker offers: the 1M-context beta is a
// Max-only entitlement, so a Pro/Free agent that selects a >200K window would send an unentitled
// beta header and fail on its first turn. We gate the presets and default off the plan instead.

// The plan tier from a raw `.credentials.json` OAuth blob, or null when absent/unparseable. During
// onboarding the blob is only ever client-side (standalone OAuth, not yet bound to an agent), so the
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
function presetAllowed(preset: ContextPreset, plan: string | null): boolean {
  return (
    preset.plans === undefined || plan === null || preset.plans.includes(plan)
  );
}

// The presets to offer and the initial selection for a context step, given the known plan (or null).
export function planContextOptions(
  context: ProviderContext,
  plan: string | null,
): { presets: ContextPreset[]; initial: number } {
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

export type ProviderKind = "claude" | "openrouter" | "zai" | "kimi" | "openai";

export type ProviderAuthKind =
  "claude_oauth" | "device_oauth" | "subscription_key" | "api_key";

export interface ProviderContextPreset {
  tokens: number;
  label: string;
  note: string;
  plans?: string[];
}

export interface ProviderContextPolicy {
  default: number;
  max: number | null;
  presets: ProviderContextPreset[];
  defaults_by_plan?: Record<string, number>;
  harness_suffix_above?: number;
}

export interface ProviderCatalogEntry {
  display: string;
  order: number;
  auth_kind: ProviderAuthKind;
  models: string[] | "live";
  model_names?: Record<string, string>;
  default_model: string | null;
  auxiliary_model?: string | null;
  context: ProviderContextPolicy;
  context_by_model?: Record<string, ProviderContextPolicy>;
}

export interface ProviderCatalog {
  default_provider: ProviderKind;
  // Partial keeps clients defensive across rolling upgrades and the server's Claude-only fallback.
  providers: Partial<Record<ProviderKind, ProviderCatalogEntry>>;
}

export type ProviderSelection =
  | {
      kind: "claude";
      credentials: string;
      model?: string;
      maxContextTokens?: number;
    }
  | {
      kind: "openrouter" | "zai" | "kimi";
      key: string;
      model: string;
      maxContextTokens?: number;
    }
  | {
      kind: "openai";
      credentials: string;
      model: string;
      maxContextTokens?: number;
    };

export type ProviderPutBody =
  | {
      kind: "claude";
      credentials: string;
      model?: string;
      max_context_tokens?: number;
    }
  | {
      kind: "openrouter" | "zai" | "kimi";
      key: string;
      model: string;
      max_context_tokens?: number;
    }
  | {
      kind: "openai";
      credentials: string;
      model: string;
      max_context_tokens?: number;
    };

export function providerPutBody(selection: ProviderSelection): ProviderPutBody {
  const context =
    selection.maxContextTokens === undefined
      ? {}
      : { max_context_tokens: selection.maxContextTokens };
  if (selection.kind === "claude") {
    return {
      kind: selection.kind,
      credentials: selection.credentials,
      ...(selection.model ? { model: selection.model } : {}),
      ...context,
    };
  }
  if (selection.kind === "openai") {
    return {
      kind: selection.kind,
      credentials: selection.credentials,
      model: selection.model,
      ...context,
    };
  }
  return {
    kind: selection.kind,
    key: selection.key,
    model: selection.model,
    ...context,
  };
}

export interface ProviderInfo {
  kind: ProviderKind | "none";
  model: string | null;
  resolved_model: string | null;
  max_context_tokens: number | null;
  authed: boolean;
  plan: string | null;
}

export interface ProviderInfoWire {
  kind?: ProviderKind;
  model?: string | null;
  resolved_model?: string | null;
  max_context_tokens?: number | null;
  authed?: boolean;
  plan?: string | null;
}

export function normalizeProviderInfo(
  provider: ProviderInfoWire,
): ProviderInfo {
  return {
    kind: provider.kind ?? "none",
    model: provider.model ?? null,
    resolved_model: provider.resolved_model ?? null,
    max_context_tokens: provider.max_context_tokens ?? null,
    authed: provider.authed ?? false,
    plan: provider.plan ?? null,
  };
}

export interface ProviderIdentity {
  kind: ProviderKind;
  providerName: string;
  modelName: string | null;
}

/// The two stable Claude aliases and their display labels. Claude's live catalog carries no
/// model_names, so this pair is the one owner of the alias set: web and mobile pickers offer it
/// as primary options and resolveProviderIdentity labels it. A live slug (e.g. "claude-opus-5")
/// is prettified by formatClaudeSlug below.
export const CLAUDE_ALIASES: { slug: string; label: string }[] = [
  { slug: "opus-latest", label: "Opus" },
  { slug: "sonnet-latest", label: "Sonnet" },
];

/// Agents provisioned before the -latest form persisted the bare alias; both spell the same
/// floating choice, so both label and canonicalize identically.
const LEGACY_CLAUDE_ALIASES: Record<string, string> = {
  opus: "opus-latest",
  sonnet: "sonnet-latest",
};

const CLAUDE_ALIAS_LABELS: Record<string, string> = {
  ...Object.fromEntries(
    CLAUDE_ALIASES.map((alias) => [alias.slug, alias.label]),
  ),
  ...Object.fromEntries(
    Object.entries(LEGACY_CLAUDE_ALIASES).map(([legacy, canonical]) => [
      legacy,
      CLAUDE_ALIASES.find((alias) => alias.slug === canonical)?.label ?? legacy,
    ]),
  ),
};

/// The canonical spelling of a Claude model selection: a legacy bare alias maps to its -latest
/// form so pickers can mark the matching button selected; anything else is already canonical.
export function canonicalClaudeModel(model: string): string {
  return LEGACY_CLAUDE_ALIASES[model] ?? model;
}

/// A modern Claude slug ("claude-opus-4-8", dated pins included) as its short display name
/// ("Opus 4.8"). A trailing 8-digit date is a snapshot pin, not a version part, so it is dropped.
/// Anything the pattern does not match (legacy version-first slugs, other providers) returns null
/// and the caller shows the raw identifier.
function formatClaudeSlug(slug: string): string | null {
  const match = /^claude-([a-z]+)((?:-\d+)+)$/.exec(slug);
  if (match?.[1] === undefined || match[2] === undefined) return null;
  const family = match[1].charAt(0).toUpperCase() + match[1].slice(1);
  const parts = match[2].slice(1).split("-");
  const last = parts[parts.length - 1];
  if (last?.length === 8) parts.pop();
  if (parts.length === 0) return null;
  return `${family} ${parts.join(".")}`;
}

/// The user-facing model label. A floating alias keeps its label until the session reports the
/// concrete model it resolved to; then the exact model wins ("Opus 4.8"). Fixed catalogs keep
/// their catalog names, and anything unrecognized shows the raw identifier.
function resolveModelName(
  provider: ProviderInfo,
  entry: ProviderCatalogEntry | undefined,
): string | null {
  const model = provider.model;
  if (!model) return null;
  const catalogName = entry?.model_names?.[model];
  if (catalogName !== undefined) return catalogName;
  const aliasLabel = CLAUDE_ALIAS_LABELS[model];
  if (aliasLabel !== undefined) {
    const resolved = provider.resolved_model
      ? formatClaudeSlug(provider.resolved_model)
      : null;
    return resolved ?? aliasLabel;
  }
  return formatClaudeSlug(model) ?? model;
}

/// Who is running this agent, as the user reads it: the catalog owns both names, and wire
/// identifiers stand in when catalog data is unavailable. Null while disconnected.
export function resolveProviderIdentity(
  provider: ProviderInfo | null,
  catalog: ProviderCatalog | undefined,
): ProviderIdentity | null {
  if (!provider || provider.kind === "none" || !provider.authed) return null;
  const entry = catalog?.providers[provider.kind];
  return {
    kind: provider.kind,
    providerName: entry?.display ?? provider.kind,
    modelName: provider.model ? resolveModelName(provider, entry) : null,
  };
}

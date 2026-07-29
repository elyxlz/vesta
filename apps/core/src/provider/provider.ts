export type ProviderKind = "claude" | "openrouter" | "zai" | "kimi" | "openai"

export type ProviderAuthKind = "claude_oauth" | "device_oauth" | "subscription_key" | "api_key"

export interface ProviderContextPreset {
  tokens: number
  label: string
  note: string
  plans?: string[]
}

export interface ProviderContextPolicy {
  default: number
  max: number | null
  presets: ProviderContextPreset[]
  defaults_by_plan?: Record<string, number>
  harness_suffix_above?: number
}

export interface ProviderManifestEntry {
  display: string
  order: number
  auth_kind: ProviderAuthKind
  models: string[] | "live"
  model_names?: Record<string, string>
  default_model: string | null
  auxiliary_model?: string | null
  context: ProviderContextPolicy
  context_by_model?: Record<string, ProviderContextPolicy>
}

export interface ProviderManifest {
  default_provider: ProviderKind
  default_personality: string
  // Partial keeps clients defensive across rolling upgrades and the server's Claude-only fallback.
  providers: Partial<Record<ProviderKind, ProviderManifestEntry>>
}

export type ProviderSelection =
  | {
      kind: "claude"
      credentials: string
      model?: string
      maxContextTokens?: number
    }
  | {
      kind: "openrouter" | "zai" | "kimi"
      key: string
      model: string
      maxContextTokens?: number
    }
  | {
      kind: "openai"
      credentials: string
      model: string
      maxContextTokens?: number
    }

export type ProviderPutBody =
  | {
      kind: "claude"
      credentials: string
      model?: string
      max_context_tokens?: number
    }
  | {
      kind: "openrouter" | "zai" | "kimi"
      key: string
      model: string
      max_context_tokens?: number
    }
  | {
      kind: "openai"
      credentials: string
      model: string
      max_context_tokens?: number
    }

export function providerPutBody(selection: ProviderSelection): ProviderPutBody {
  const context =
    selection.maxContextTokens === undefined
      ? {}
      : { max_context_tokens: selection.maxContextTokens }
  if (selection.kind === "claude") {
    return {
      kind: selection.kind,
      credentials: selection.credentials,
      ...(selection.model ? { model: selection.model } : {}),
      ...context,
    }
  }
  if (selection.kind === "openai") {
    return {
      kind: selection.kind,
      credentials: selection.credentials,
      model: selection.model,
      ...context,
    }
  }
  return {
    kind: selection.kind,
    key: selection.key,
    model: selection.model,
    ...context,
  }
}

export interface ProviderInfo {
  kind: ProviderKind | "none"
  model: string | null
  max_context_tokens: number | null
  authed: boolean
  plan: string | null
}

export interface ProviderInfoWire {
  kind?: ProviderKind
  model?: string | null
  max_context_tokens?: number | null
  authed?: boolean
  plan?: string | null
}

export function normalizeProviderInfo(provider: ProviderInfoWire): ProviderInfo {
  return {
    kind: provider.kind ?? "none",
    model: provider.model ?? null,
    max_context_tokens: provider.max_context_tokens ?? null,
    authed: provider.authed ?? false,
    plan: provider.plan ?? null,
  }
}

export interface ProviderIdentity {
  kind: ProviderKind
  providerName: string
  modelName: string | null
}

/// Who is running this agent, as the user reads it: the manifest owns both names, and the wire
/// identifiers stand in on a gateway whose manifest predates them. Null while disconnected.
export function resolveProviderIdentity(
  provider: ProviderInfo | null,
  manifest: ProviderManifest | undefined,
): ProviderIdentity | null {
  if (!provider || provider.kind === "none" || !provider.authed) return null
  const entry = manifest?.providers[provider.kind]
  return {
    kind: provider.kind,
    providerName: entry?.display ?? provider.kind,
    modelName: provider.model ? (entry?.model_names?.[provider.model] ?? provider.model) : null,
  }
}

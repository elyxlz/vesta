import type {
  ProviderKind,
  ClaudeOAuthStart,
  OpenAIOAuthStart,
  ProviderCatalog,
  ProviderSelection,
} from "@vesta/core";
import { startClaudeOAuth, startOpenAIOAuth } from "@vesta/core";
import { httpClient } from "@/api/client";

export type AuthStartResult = ClaudeOAuthStart | OpenAIOAuthStart;

const KEY_STEP_COPY = {
  openrouter: {
    title: "OpenRouter API key",
    subtitle: "paste a key from openrouter.ai/keys. it stays on this machine.",
    placeholder: "sk-or-v1-...",
  },
  zai: {
    title: "Z.AI subscription key",
    subtitle:
      "paste your Coding Plan subscription key. it stays on this machine.",
    placeholder: "Z.AI subscription key",
  },
  kimi: {
    title: "Kimi Code subscription key",
    subtitle: "paste your Kimi membership key. it stays on this machine.",
    placeholder: "Kimi Code subscription key",
  },
} as const;

export function keyStepCopy(provider: ProviderKind | null) {
  if (provider === "claude" || provider === "openai" || provider === null)
    return KEY_STEP_COPY.openrouter;
  return KEY_STEP_COPY[provider];
}

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

// The initial model-step selection: the in-progress choice wins, else Claude
// defaults to the "opus-latest" alias, else the catalog's per-provider default.

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

// A live-catalog provider has no static default model, so even defaults-only
// mode must walk the model (and context) steps.

// A live-catalog provider has no static default model, so even defaults-only
// mode must walk the model (and context) steps.

// A live-catalog provider has no static default model, so even defaults-only
// mode must walk the model (and context) steps.
export function catalogIsLive(
  provider: ProviderKind | null,
  catalog: ProviderCatalog,
): boolean {
  if (provider === null) return false;
  return catalog.providers[provider]?.models === "live";
}

export function startProviderOAuth(
  agentName: string,
  provider: ProviderKind | null,
) {
  if (provider === "openai") return startOpenAIOAuth(httpClient, agentName);
  if (provider === "claude") return startClaudeOAuth(httpClient, agentName);
  return Promise.reject(
    new Error(`no OAuth adapter for ${provider ?? "none"}`),
  );
}

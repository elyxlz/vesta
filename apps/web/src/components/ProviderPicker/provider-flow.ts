import type {
  ProviderKind,
  ClaudeOAuthStart,
  OpenAIOAuthStart,
  ProviderCatalog,
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

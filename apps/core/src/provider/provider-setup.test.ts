import { describe, expect, it } from "vitest";
import {
  modelStepInitialModel,
  planContextOptions,
  planFromCredentials,
  providerResult,
  providerUsesOAuth,
} from "./provider-setup";
import type {
  ProviderCatalog,
  ProviderCatalogEntry,
  ProviderContextPolicy,
} from "./provider";

const claudeContext: ProviderContextPolicy = {
  default: 1000000,
  max: 1000000,
  defaults_by_plan: { max: 1000000, pro: 200000, free: 200000 },
  presets: [
    { tokens: 1000000, label: "1M", note: "most context", plans: ["max"] },
    { tokens: 500000, label: "500K", note: "balanced", plans: ["max"] },
    { tokens: 200000, label: "200K", note: "cheapest" },
  ],
};

// A plan default that names a window the plan itself cannot see, so the
// picker must fall through to the provider default, then the smallest preset.
const misconfiguredContext: ProviderContextPolicy = {
  default: 1000000,
  max: 1000000,
  defaults_by_plan: { pro: 1000000 },
  presets: [
    { tokens: 1000000, label: "1M", note: "most context", plans: ["max"] },
    { tokens: 500000, label: "500K", note: "balanced" },
    { tokens: 200000, label: "200K", note: "cheapest" },
  ],
};

const openrouterContext: ProviderContextPolicy = {
  default: 200000,
  max: 200000,
  presets: [
    { tokens: 200000, label: "200K", note: "full window" },
    { tokens: 64000, label: "64K", note: "cheapest" },
  ],
};

describe("planContextOptions", () => {
  it.each<{
    name: string;
    context: ProviderContextPolicy;
    plan: "max" | "pro" | "free" | null;
    tokens: number[];
    initial: number;
  }>([
    {
      name: "offers every window and defaults to 1M for max",
      context: claudeContext,
      plan: "max",
      tokens: [1000000, 500000, 200000],
      initial: 1000000,
    },
    {
      name: "hides >200K windows and defaults to 200K for pro",
      context: claudeContext,
      plan: "pro",
      tokens: [200000],
      initial: 200000,
    },
    {
      name: "hides >200K windows and defaults to 200K for free",
      context: claudeContext,
      plan: "free",
      tokens: [200000],
      initial: 200000,
    },
    {
      name: "is permissive when the plan is unknown",
      context: claudeContext,
      plan: null,
      tokens: [1000000, 500000, 200000],
      initial: 1000000,
    },
    {
      name: "leaves an ungated provider unchanged",
      context: openrouterContext,
      plan: null,
      tokens: [200000, 64000],
      initial: 200000,
    },
    {
      name: "falls back to the smallest visible preset when both the plan default and provider default are hidden",
      context: misconfiguredContext,
      plan: "pro",
      tokens: [500000, 200000],
      initial: 200000,
    },
    {
      name: "falls back to the provider default when only the plan default is hidden",
      context: { ...misconfiguredContext, default: 500000 },
      plan: "pro",
      tokens: [500000, 200000],
      initial: 500000,
    },
  ])("$name", ({ context, plan, tokens, initial }) => {
    const result = planContextOptions(context, plan);
    expect(result.presets.map((preset) => preset.tokens)).toEqual(tokens);
    expect(result.initial).toBe(initial);
  });
});

describe("planFromCredentials", () => {
  it("reads subscriptionType from a claude OAuth blob", () => {
    expect(
      planFromCredentials(
        JSON.stringify({ claudeAiOauth: { subscriptionType: "max" } }),
      ),
    ).toBe("max");
  });

  it.each([
    ["the field is absent", JSON.stringify({ claudeAiOauth: {} })],
    ["the blob is absent", JSON.stringify({})],
    ["the JSON is unparseable", "not json"],
  ])("returns null when %s", (_name, blob) => {
    expect(planFromCredentials(blob)).toBeNull();
  });
});

function catalogEntry(
  overrides: Partial<ProviderCatalogEntry>,
): ProviderCatalogEntry {
  return {
    display: "Provider",
    order: 1,
    auth_kind: "api_key",
    models: [],
    default_model: null,
    context: { default: 200000, max: null, presets: [] },
    ...overrides,
  };
}

const setupCatalog: ProviderCatalog = {
  default_provider: "claude",
  providers: {
    claude: catalogEntry({ auth_kind: "claude_oauth", models: "live" }),
    openai: catalogEntry({ auth_kind: "device_oauth", default_model: "gpt" }),
    zai: catalogEntry({ auth_kind: "subscription_key", default_model: "glm" }),
  },
};

describe("providerResult", () => {
  it("waits for credentials before an OAuth provider can finish", () => {
    expect(providerResult("claude", null, "", "opus-latest", 0)).toBeNull();
    expect(providerResult("openai", null, "", "gpt", 0)).toBeNull();
  });

  it("builds a Claude selection from the stashed credentials", () => {
    expect(providerResult("claude", "blob", "", "", 200000)).toEqual({
      kind: "claude",
      credentials: "blob",
      model: undefined,
      maxContextTokens: 200000,
    });
  });

  it("leaves a zero context off a key provider's selection", () => {
    expect(providerResult("openrouter", null, "sk", "vendor/model", 0)).toEqual(
      { kind: "openrouter", key: "sk", model: "vendor/model" },
    );
  });
});

describe("modelStepInitialModel", () => {
  it.each([
    ["an in-progress choice", "zai", "glm-air", "glm-air"],
    ["the Claude alias", "claude", "", "opus-latest"],
    ["the catalog default", "zai", "", "glm"],
    ["nothing without a provider", null, "", ""],
  ] as const)("starts from %s", (_case, provider, model, expected) => {
    expect(modelStepInitialModel(provider, model, setupCatalog)).toBe(expected);
  });
});

describe("providerUsesOAuth", () => {
  it.each([
    ["claude", true],
    ["openai", true],
    ["zai", false],
    [null, false],
  ] as const)("answers %s with %s", (provider, expected) => {
    expect(providerUsesOAuth(provider, setupCatalog)).toBe(expected);
  });
});

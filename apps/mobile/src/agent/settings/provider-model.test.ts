import { describe, expect, it } from "vitest";
import type { ProviderCatalogEntry } from "@vesta/core";
import {
  CLAUDE_ALIAS_OPTIONS,
  buildModelOptions,
  contextLabel,
  contextPolicyToOffer,
  sortAdvertisedProviders,
} from "./provider-model";

function entryOf(
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

describe("sortAdvertisedProviders", () => {
  it("orders providers by their manifest order", () => {
    const providers = {
      kimi: entryOf({ order: 3 }),
      claude: entryOf({ order: 1 }),
      zai: entryOf({ order: 2 }),
    };
    expect(sortAdvertisedProviders(providers)).toEqual([
      "claude",
      "zai",
      "kimi",
    ]);
  });

  it("advertises nothing from an empty manifest", () => {
    expect(sortAdvertisedProviders({})).toEqual([]);
  });
});

describe("buildModelOptions", () => {
  const liveModels = [
    { slug: "vendor/model-a", label: "Model A" },
    { slug: "vendor/model-b", label: "Model B" },
  ];

  it("serves OpenRouter's live list", () => {
    const options = buildModelOptions(
      "openrouter",
      entryOf({ models: "live" }),
      liveModels,
      undefined,
    );
    expect(options).toEqual([
      { label: "Model A", value: "vendor/model-a" },
      { label: "Model B", value: "vendor/model-b" },
    ]);
  });

  it("serves nothing while the OpenRouter list has not loaded", () => {
    expect(
      buildModelOptions(
        "openrouter",
        entryOf({ models: "live" }),
        undefined,
        undefined,
      ),
    ).toEqual([]);
  });

  it("serves Claude's live catalog, with the aliases kept apart", () => {
    const options = buildModelOptions(
      "claude",
      entryOf({ models: "live" }),
      undefined,
      [{ slug: "claude-opus-5", label: "Opus 5" }],
    );
    expect(options).toEqual([{ label: "Opus 5", value: "claude-opus-5" }]);
    expect(CLAUDE_ALIAS_OPTIONS).toEqual([
      { label: "Opus", value: "opus-latest" },
      { label: "Sonnet", value: "sonnet-latest" },
    ]);
  });

  it("labels a fixed catalog from the manifest's model names", () => {
    const options = buildModelOptions(
      "kimi",
      entryOf({
        models: ["kimi-for-coding", "kimi-unlabeled"],
        model_names: { "kimi-for-coding": "Kimi For Coding" },
      }),
      undefined,
      undefined,
    );
    expect(options).toEqual([
      { label: "Kimi For Coding", value: "kimi-for-coding" },
      { label: "kimi-unlabeled", value: "kimi-unlabeled" },
    ]);
  });

  it("serves nothing for a fixed provider missing from the manifest", () => {
    expect(buildModelOptions("zai", undefined, undefined, undefined)).toEqual(
      [],
    );
  });

  it("serves nothing for a fixed provider whose manifest says live", () => {
    expect(
      buildModelOptions(
        "zai",
        entryOf({ models: "live" }),
        undefined,
        undefined,
      ),
    ).toEqual([]);
  });
});

describe("contextPolicyToOffer", () => {
  const presets = [{ tokens: 200000, label: "200K", note: "cheapest" }];

  it("offers nothing for OpenRouter, whose models carry their own limit", () => {
    const entry = entryOf({
      context: { default: 200000, max: null, presets },
    });
    expect(contextPolicyToOffer("openrouter", entry, "vendor/model")).toBe(
      null,
    );
  });

  it("offers nothing when the policy has no presets", () => {
    expect(contextPolicyToOffer("zai", entryOf({}), "glm")).toBe(null);
  });

  it("prefers the chosen model's own policy", () => {
    const own = { default: 128000, max: null, presets };
    const entry = entryOf({
      context: { default: 200000, max: null, presets },
      context_by_model: { glm: own },
    });
    expect(contextPolicyToOffer("zai", entry, "glm")).toBe(own);
  });
});

describe("contextLabel", () => {
  const policy = {
    default: 200000,
    max: null,
    presets: [{ tokens: 1000000, label: "1M", note: "most context" }],
  };

  it("uses the preset's label when one matches", () => {
    expect(contextLabel(1000000, policy)).toBe("1M");
  });

  it.each([
    [200000, "200K"],
    [2000000, "2M"],
  ])("formats %d tokens as %s", (tokens, expected) => {
    expect(contextLabel(tokens, policy)).toBe(expected);
  });
});

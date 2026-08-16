import { describe, expect, it } from "vitest";
import type { ProviderManifestEntry } from "@vesta/core";
import {
  buildModelOptions,
  resolveProviderKind,
  sortAdvertisedProviders,
} from "./provider-model";

function entryOf(overrides: Partial<ProviderManifestEntry>): ProviderManifestEntry {
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

describe("resolveProviderKind", () => {
  it("uses the picked kind while no provider is signed in", () => {
    expect(resolveProviderKind("none", "openrouter")).toBe("openrouter");
  });

  it("lets the signed-in provider win over the picker", () => {
    expect(resolveProviderKind("claude", "openrouter")).toBe("claude");
  });
});

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

  it("offers the Claude aliases ahead of the live catalog", () => {
    const options = buildModelOptions(
      "claude",
      entryOf({ models: "live" }),
      undefined,
      [{ slug: "claude-opus-5", label: "Opus 5" }],
    );
    expect(options).toEqual([
      { label: "Opus", value: "opus-latest" },
      { label: "Sonnet", value: "sonnet-latest" },
      { label: "Opus 5", value: "claude-opus-5" },
    ]);
  });

  it("still offers the Claude aliases while the live fetch has not resolved", () => {
    const options = buildModelOptions(
      "claude",
      entryOf({ models: "live" }),
      undefined,
      undefined,
    );
    expect(options).toEqual([
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

import { describe, expect, it } from "vitest"
import {
  canonicalClaudeModel,
  normalizeProviderInfo,
  providerPutBody,
  resolveProviderIdentity,
  type ProviderSelection,
} from "./provider"

describe("providerPutBody", () => {
  it.each<[ProviderSelection, object]>([
    [
      {
        kind: "claude",
        credentials: "oauth",
        model: "opus",
        maxContextTokens: 200_000,
      },
      {
        kind: "claude",
        credentials: "oauth",
        model: "opus",
        max_context_tokens: 200_000,
      },
    ],
    [
      { kind: "kimi", key: "key", model: "k3" },
      { kind: "kimi", key: "key", model: "k3" },
    ],
    [
      {
        kind: "openai",
        credentials: "oauth",
        model: "gpt-5.6-sol",
        maxContextTokens: 272_000,
      },
      {
        kind: "openai",
        credentials: "oauth",
        model: "gpt-5.6-sol",
        max_context_tokens: 272_000,
      },
    ],
  ])("maps %s to the API contract", (selection, expected) => {
    expect(providerPutBody(selection)).toEqual(expected)
  })
})

describe("normalizeProviderInfo", () => {
  it("normalizes an unprovisioned response once for every client", () => {
    expect(normalizeProviderInfo({ authed: false })).toEqual({
      kind: "none",
      model: null,
      resolved_model: null,
      max_context_tokens: null,
      authed: false,
      plan: null,
    })
  })
})

describe("resolveProviderIdentity", () => {
  it("resolves provider and model display names from the manifest", () => {
    expect(
      resolveProviderIdentity(
        {
          kind: "openai",
          model: "gpt-5.6-sol",
          resolved_model: null,
          max_context_tokens: null,
          authed: true,
          plan: null,
        },
        {
          default_provider: "openai",
          default_personality: "dry",
          providers: {
            openai: {
              display: "OpenAI",
              order: 0,
              auth_kind: "device_oauth",
              models: ["gpt-5.6-sol"],
              model_names: { "gpt-5.6-sol": "GPT 5.6 Sol" },
              default_model: "gpt-5.6-sol",
              context: { default: 0, max: null, presets: [] },
            },
          },
        },
      ),
    ).toEqual({
      kind: "openai",
      providerName: "OpenAI",
      modelName: "GPT 5.6 Sol",
    })
  })

  it("labels a live Claude alias when the manifest carries no model_names", () => {
    const provider = {
      kind: "claude" as const,
      model: "opus",
      resolved_model: null,
      max_context_tokens: null,
      authed: true,
      plan: null,
    }
    const manifest = {
      default_provider: "claude" as const,
      default_personality: "dry",
      providers: {
        claude: {
          display: "Claude",
          order: 0,
          auth_kind: "claude_oauth" as const,
          models: "live" as const,
          default_model: null,
          context: { default: 1_000_000, max: 1_000_000, presets: [] },
        },
      },
    }
    expect(resolveProviderIdentity(provider, manifest)).toEqual({
      kind: "claude",
      providerName: "Claude",
      modelName: "Opus",
    })
    expect(resolveProviderIdentity({ ...provider, model: "claude-opus-5" }, manifest)).toEqual({
      kind: "claude",
      providerName: "Claude",
      modelName: "Opus 5",
    })
    expect(
      resolveProviderIdentity({ ...provider, model: "claude-opus-4-8" }, manifest)?.modelName,
    ).toBe("Opus 4.8")
    expect(
      resolveProviderIdentity({ ...provider, model: "claude-haiku-4-5-20251001" }, manifest)
        ?.modelName,
    ).toBe("Haiku 4.5")
    expect(
      resolveProviderIdentity({ ...provider, model: "claude-3-5-sonnet-20241022" }, manifest)
        ?.modelName,
    ).toBe("claude-3-5-sonnet-20241022")
    expect(
      resolveProviderIdentity({ ...provider, resolved_model: "claude-opus-4-8" }, manifest)
        ?.modelName,
    ).toBe("Opus 4.8")
    expect(
      resolveProviderIdentity({ ...provider, model: "opus-latest" }, manifest)?.modelName,
    ).toBe("Opus")
    expect(
      resolveProviderIdentity(
        { ...provider, model: "sonnet-latest", resolved_model: "claude-sonnet-5" },
        manifest,
      )?.modelName,
    ).toBe("Sonnet 5")
  })

  it("falls back to wire identifiers and hides disconnected providers", () => {
    const provider = {
      kind: "openrouter" as const,
      model: "author/model",
      resolved_model: null,
      max_context_tokens: null,
      authed: true,
      plan: null,
    }
    expect(resolveProviderIdentity(provider, undefined)).toMatchObject({
      providerName: "openrouter",
      modelName: "author/model",
    })
    expect(resolveProviderIdentity({ ...provider, authed: false }, undefined)).toBeNull()
  })
})

describe("canonicalClaudeModel", () => {
  it("maps legacy bare aliases to the -latest form and leaves the rest alone", () => {
    expect(canonicalClaudeModel("opus")).toBe("opus-latest")
    expect(canonicalClaudeModel("sonnet")).toBe("sonnet-latest")
    expect(canonicalClaudeModel("opus-latest")).toBe("opus-latest")
    expect(canonicalClaudeModel("claude-opus-4-8")).toBe("claude-opus-4-8")
  })
})

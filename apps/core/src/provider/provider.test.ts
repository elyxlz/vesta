import { describe, expect, it } from "vitest"
import {
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

  it("falls back to wire identifiers and hides disconnected providers", () => {
    const provider = {
      kind: "openrouter" as const,
      model: "author/model",
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

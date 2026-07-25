import { describe, expect, it } from "vitest"
import { normalizeProviderInfo, providerPutBody, type ProviderSelection } from "./provider"

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

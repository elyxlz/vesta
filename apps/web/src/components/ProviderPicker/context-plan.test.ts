import { describe, expect, it } from "vitest";
import type { ProviderContext } from "@/api/manifest";
import { planContextOptions, planFromCredentials } from "./context-plan";

const claudeContext: ProviderContext = {
  default: 1000000,
  defaults_by_plan: { max: 1000000, pro: 200000, free: 200000 },
  presets: [
    { tokens: 1000000, label: "1M", note: "most context", plans: ["max"] },
    { tokens: 500000, label: "500K", note: "balanced", plans: ["max"] },
    { tokens: 200000, label: "200K", note: "cheapest" },
  ],
};

describe("planContextOptions", () => {
  it("offers every window and defaults to 1M for max", () => {
    const { presets, initial } = planContextOptions(claudeContext, "max");
    expect(presets.map((preset) => preset.tokens)).toEqual([
      1000000, 500000, 200000,
    ]);
    expect(initial).toBe(1000000);
  });

  it("hides >200K windows and defaults to 200K for pro", () => {
    const { presets, initial } = planContextOptions(claudeContext, "pro");
    expect(presets.map((preset) => preset.tokens)).toEqual([200000]);
    expect(initial).toBe(200000);
  });

  it("hides >200K windows and defaults to 200K for free", () => {
    const { presets, initial } = planContextOptions(claudeContext, "free");
    expect(presets.map((preset) => preset.tokens)).toEqual([200000]);
    expect(initial).toBe(200000);
  });

  it("is permissive when the plan is unknown", () => {
    const { presets, initial } = planContextOptions(claudeContext, null);
    expect(presets.map((preset) => preset.tokens)).toEqual([
      1000000, 500000, 200000,
    ]);
    expect(initial).toBe(1000000);
  });

  it("leaves an ungated provider unchanged", () => {
    const openrouter: ProviderContext = {
      default: 200000,
      presets: [
        { tokens: 200000, label: "200K", note: "full window" },
        { tokens: 64000, label: "64K", note: "cheapest" },
      ],
    };
    const { presets, initial } = planContextOptions(openrouter, null);
    expect(presets.map((preset) => preset.tokens)).toEqual([200000, 64000]);
    expect(initial).toBe(200000);
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

  it("returns null when the field, blob, or JSON is absent", () => {
    expect(
      planFromCredentials(JSON.stringify({ claudeAiOauth: {} })),
    ).toBeNull();
    expect(planFromCredentials(JSON.stringify({}))).toBeNull();
    expect(planFromCredentials("not json")).toBeNull();
  });
});

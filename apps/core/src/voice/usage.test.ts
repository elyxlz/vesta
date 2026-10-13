import { describe, expect, it } from "vitest";

import { sttUsageSummary, ttsUsage } from "./usage";

describe("sttUsageSummary", () => {
  it("adds the hours and shows the balance left", () => {
    expect(
      sttUsageSummary({
        usage: { results: [{ hours: 3.25 }, { hours: 1.5 }, {}] },
        balance: { balances: [{ amount: 187.42, units: "usd" }] },
      }),
    ).toBe("4.75 h used · $187.42 left");
  });

  it("shows a balance in hours", () => {
    expect(
      sttUsageSummary({
        usage: { results: [] },
        balance: { balances: [{ amount: 12, units: "hours" }] },
      }),
    ).toBe("0.00 h used · 12.00 h left");
  });

  it.each([
    [undefined],
    [null],
    [{}],
    [{ usage: { results: [{ hours: 1 }] } }],
    [{ balance: { balances: [{ amount: 1, units: "usd" }] } }],
    [{ usage: { results: [{ hours: 1 }] }, balance: { balances: [] } }],
  ])("shows a dash until the provider gives both numbers", (usage) => {
    expect(sttUsageSummary(usage)).toBe("—");
  });
});

describe("ttsUsage", () => {
  it("shows the characters used of the limit", () => {
    expect(
      ttsUsage({ usage: { character_count: 12450, character_limit: 100000 } }),
    ).toEqual({ kind: "characters", value: "12,450 / 100,000" });
  });

  it("shows the balance of a provider with no character quota", () => {
    expect(
      ttsUsage({ usage: { balances: [{ amount: 8.5, units: "USD" }] } }),
    ).toEqual({ kind: "balance", value: "$8.50 left" });
  });

  it("names an unknown unit after the amount", () => {
    expect(
      ttsUsage({ usage: { balances: [{ amount: 3, units: "credits" }] } }),
    ).toEqual({ kind: "balance", value: "3.00 credits left" });
  });

  it.each([[undefined], [null], [{}], [{ usage: { character_count: 480 } }]])(
    "shows a dash when the provider gives no numbers",
    (usage) => {
      expect(ttsUsage(usage)).toEqual({ kind: "characters", value: "—" });
    },
  );
});

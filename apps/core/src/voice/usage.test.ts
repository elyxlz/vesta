import { describe, expect, it } from "vitest";

import { voiceUsageSummary } from "./usage";

describe("voiceUsageSummary", () => {
  it.each([
    [
      {
        used: { amount: 4.75, unit: "hours" },
        left: { amount: 187.42, unit: "usd" },
      },
      "4.75 h used · $187.42 left",
    ],
    [
      {
        used: { amount: 12450, unit: "credits" },
        left: { amount: 87550, unit: "credits" },
      },
      "12,450 credits used · 87,550 credits left",
    ],
    [{ used: null, left: { amount: 8.5, unit: "usd" } }, "$8.50 left"],
    [{ used: { amount: 2, unit: "hours" }, left: null }, "2.00 h used"],
    [{ used: null, left: { amount: 3, unit: "minutes" } }, "3.00 minutes left"],
  ])("says what the provider gives (%j)", (usage, expected) => {
    expect(voiceUsageSummary(usage)).toBe(expected);
  });

  it.each([[undefined], [null], [{ used: null, left: null }]])(
    "shows a dash when the provider gives no number",
    (usage) => {
      expect(voiceUsageSummary(usage)).toBe("—");
    },
  );
});

import { describe, expect, it } from "vitest";

import type { SettingDef } from "../api/voice";
import { formatSettingNumber } from "./setting-format";

function numberSetting(unit?: string): SettingDef {
  return { key: "k", type: "number", label: "k", value: 0, unit };
}

describe("formatSettingNumber", () => {
  it.each([
    [numberSetting("ms"), 1500, "1.5s"],
    [numberSetting("ms"), 500, "0.5s"],
    [numberSetting(), 0.8, "0.80"],
    [numberSetting("x"), 1, "1.00"],
  ])("reads %j at %d as %s", (setting, value, expected) => {
    expect(formatSettingNumber(setting, value)).toBe(expected);
  });
});

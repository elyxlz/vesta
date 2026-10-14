import { describe, expect, it } from "vitest";
import type { SettingDef, VoiceSettingsData } from "@vesta/core";
import {
  filterOptions,
  findSetting,
  formatNumber,
  numberRange,
  numberValue,
  parseSettingSection,
  selectedOptionLabel,
} from "./voice-settings-model";

const VOICES = [
  {
    value: "aura-2-apollo-en",
    label: "Apollo",
    description: "American English, masculine: confident, casual",
  },
  {
    value: "aura-2-athena-en",
    label: "Athena",
    description: "American English, feminine: calm, smooth",
  },
  { value: "aura-2-estrella-es", label: "Estrella" },
];

function setting(fields: Partial<SettingDef>): SettingDef {
  return {
    key: "voice",
    type: "select",
    label: "Voice",
    value: null,
    ...fields,
  };
}

describe("filterOptions", () => {
  it("returns every option for an empty query", () => {
    expect(filterOptions(VOICES, "  ")).toEqual(VOICES);
  });

  it("matches the label in any letter case", () => {
    expect(filterOptions(VOICES, "ATH").map((o) => o.label)).toEqual([
      "Athena",
    ]);
  });

  it("matches the description in any letter case", () => {
    expect(filterOptions(VOICES, "Masculine").map((o) => o.label)).toEqual([
      "Apollo",
    ]);
  });

  it("does not match the stored value of an option", () => {
    expect(filterOptions(VOICES, "aura-2")).toEqual([]);
  });

  it("keeps an option with no description out of a description match", () => {
    expect(filterOptions(VOICES, "english").map((o) => o.label)).toEqual([
      "Apollo",
      "Athena",
    ]);
  });
});

describe("selectedOptionLabel", () => {
  it("names the chosen option by its label", () => {
    expect(
      selectedOptionLabel(
        setting({ value: "aura-2-athena-en", options: VOICES }),
      ),
    ).toBe("Athena");
  });

  it("shows the stored value when no option carries it", () => {
    expect(
      selectedOptionLabel(setting({ value: "custom", options: VOICES })),
    ).toBe("custom");
  });
});

describe("number settings", () => {
  it("reads the range of a setting", () => {
    expect(numberRange(setting({ min: 500, max: 10000, step: 500 }))).toEqual({
      min: 500,
      max: 10000,
      step: 500,
    });
  });

  it("falls back to zero to one in hundredths", () => {
    expect(numberRange(setting({}))).toEqual({ min: 0, max: 1, step: 0.01 });
  });

  it("reads the value, then the default, then the minimum", () => {
    expect(numberValue(setting({ value: 0.4, default: 0.7 }))).toBe(0.4);
    expect(numberValue(setting({ default: 0.7 }))).toBe(0.7);
    expect(numberValue(setting({ min: 0.2 }))).toBe(0.2);
  });

  it("shows milliseconds as seconds with one decimal", () => {
    expect(formatNumber(setting({ unit: "ms" }), 5000)).toBe("5.0s");
    expect(formatNumber(setting({ unit: "ms" }), 1500)).toBe("1.5s");
  });

  it("shows every other number with two decimals", () => {
    expect(formatNumber(setting({}), 0.7)).toBe("0.70");
    expect(formatNumber(setting({ unit: "s" }), 1.25)).toBe("1.25");
  });
});

describe("finding a setting from a route", () => {
  const voice = setting({ key: "voice" });
  const bargeIn = setting({ key: "barge_in", type: "bool", value: true });
  const data: VoiceSettingsData = {
    stt: { configured: true, provider: "deepgram", settings: [] },
    tts: { configured: true, provider: "deepgram", settings: [voice] },
    judge: null,
    behaviors: { settings: [bargeIn] },
  };

  it.each([
    ["stt", "stt"],
    ["tts", "tts"],
    ["judge", "judge"],
    ["behavior", "behavior"],
    ["usage", null],
    [undefined, null],
  ])("reads the section %s", (value, expected) => {
    expect(parseSettingSection(value)).toBe(expected);
  });

  it("finds a setting of a role and a behavior", () => {
    expect(findSetting(data, "tts", "voice")).toBe(voice);
    expect(findSetting(data, "behavior", "barge_in")).toBe(bargeIn);
  });

  it("answers null for an unknown key and for a role with no service", () => {
    expect(findSetting(data, "tts", "speed")).toBeNull();
    expect(findSetting(data, "judge", "voice")).toBeNull();
  });
});

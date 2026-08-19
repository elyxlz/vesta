import { describe, expect, it } from "vitest";
import {
  AGENT_SETTINGS_SECTIONS,
  findSection,
  sectionTitle,
} from "./sections-model";

describe("sectionTitle", () => {
  it.each([
    ["general", "General"],
    ["provider", "Provider and model"],
    ["voice", "Voice"],
    ["notifications", "Notification rules"],
    ["files", "Files"],
    ["host-access", "Host access"],
    ["backups", "Backups"],
  ])("titles %s as %s", (key, title) => {
    expect(sectionTitle(key)).toBe(title);
  });

  it("falls back to Settings for a key it does not know", () => {
    expect(sectionTitle("time-travel")).toBe("Settings");
  });
});

describe("findSection", () => {
  it("finds every section, carrying it for content lookup", () => {
    for (const section of AGENT_SETTINGS_SECTIONS) {
      expect(findSection(section.key)).toEqual(section);
    }
  });

  it("returns null for an unknown deep-link key", () => {
    expect(findSection("time-travel")).toBeNull();
  });
});

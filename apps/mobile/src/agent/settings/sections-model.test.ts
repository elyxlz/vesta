import { describe, expect, it } from "vitest";
import {
  AGENT_SETTINGS_SECTIONS,
  sectionAvailability,
  sectionTitle,
  showsAdvancedSections,
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

describe("showsAdvancedSections", () => {
  it.each([
    ["ios", true],
    ["android", false],
    [undefined, false],
  ])("on %s answers %s", (os, shows) => {
    expect(showsAdvancedSections(os)).toBe(shows);
  });
});

describe("sectionAvailability", () => {
  it("serves every section on iOS", () => {
    for (const section of AGENT_SETTINGS_SECTIONS) {
      expect(sectionAvailability(section.key, "ios")).toBe("available");
    }
  });

  it.each([
    ["general", "available"],
    ["provider", "hidden"],
    ["voice", "hidden"],
    ["notifications", "hidden"],
    ["files", "hidden"],
    ["host-access", "hidden"],
    ["backups", "hidden"],
  ])("on Android answers %s -> %s", (key, availability) => {
    expect(sectionAvailability(key, "android")).toBe(availability);
  });

  it("reports an unknown key on both platforms", () => {
    expect(sectionAvailability("time-travel", "ios")).toBe("unknown");
    expect(sectionAvailability("time-travel", "android")).toBe("unknown");
  });
});

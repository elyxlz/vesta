import { describe, expect, it } from "vitest";
import {
  blocksProtectedContent,
  initialPrivacySettings,
  locksApp,
  protectsAppSwitcher,
  readPrivacySettings,
} from "./model";

describe("privacy settings", () => {
  it("defaults privacy features off", () => {
    expect(readPrivacySettings(null)).toEqual(initialPrivacySettings);
    expect(readPrivacySettings("not json")).toEqual(initialPrivacySettings);
  });

  it("restores valid fields without trusting malformed values", () => {
    expect(
      readPrivacySettings(
        JSON.stringify({
          appLockEnabled: true,
          hideAppSwitcherPreview: "yes",
        }),
      ),
    ).toEqual({
      appLockEnabled: true,
      hideAppSwitcherPreview: false,
    });
  });

  it("protects app-switcher content whenever either privacy feature needs it", () => {
    expect(protectsAppSwitcher(initialPrivacySettings)).toBe(false);
    expect(
      protectsAppSwitcher({
        appLockEnabled: true,
        hideAppSwitcherPreview: false,
      }),
    ).toBe(true);
    expect(
      protectsAppSwitcher({
        appLockEnabled: false,
        hideAppSwitcherPreview: true,
      }),
    ).toBe(true);
  });

  it("locks only after a true background transition", () => {
    expect(locksApp("active")).toBe(false);
    expect(locksApp("inactive")).toBe(false);
    expect(locksApp("background")).toBe(true);
  });

  it("blocks protected content until settings are hydrated and unlocked", () => {
    expect(blocksProtectedContent(false, true)).toBe(true);
    expect(blocksProtectedContent(false, false)).toBe(true);
    expect(blocksProtectedContent(true, true)).toBe(true);
    expect(blocksProtectedContent(true, false)).toBe(false);
  });
});

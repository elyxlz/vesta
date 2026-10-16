import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  authedUrl: vi.fn(),
  httpClient: {},
  websocketUrl: vi.fn(),
}));

const { microphoneDeniedMessage } = await import("./voice");

describe("microphoneDeniedMessage", () => {
  it.each([
    { isDesktopApp: true, platform: "macos", expected: "System Settings" },
    { isDesktopApp: true, platform: "windows", expected: "Settings > Privacy" },
    { isDesktopApp: false, platform: "macos", expected: "browser settings" },
    { isDesktopApp: false, platform: "windows", expected: "browser settings" },
  ] as const)(
    "names where to turn it on ($platform, desktop app: $isDesktopApp)",
    ({ isDesktopApp, platform, expected }) => {
      expect(microphoneDeniedMessage({ isDesktopApp, platform })).toContain(
        expected,
      );
    },
  );
});

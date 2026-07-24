import { describe, expect, it, vi } from "vitest";
import { checkForAppUpdate, isNewerVersion, selectLinuxAsset } from "./updater";

// A stand-in for electron-updater's autoUpdater that records the event handlers the code
// registers, so the test can assert an "error" handler exists and swallows.
const updaterMock = vi.hoisted(() => {
  const handlers: Record<string, (arg: unknown) => void> = {};
  const autoUpdater = {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    allowDowngrade: true,
    on(event: string, cb: (arg: unknown) => void): void {
      handlers[event] = cb;
    },
    setFeedURL(): void {
      /* noop */
    },
    checkForUpdates(): Promise<null> {
      return Promise.resolve(null);
    },
  };
  return { autoUpdater, handlers };
});

vi.mock("electron-updater", () => ({
  default: { autoUpdater: updaterMock.autoUpdater },
}));
vi.mock("electron", () => ({
  app: { getPath: () => "/tmp", getVersion: () => "0.1.0" },
}));

const asset = (name: string) => ({
  name,
  browser_download_url: `https://example.test/${name}`,
});

const RELEASE = [
  "Vesta_0.1.176_amd64.deb",
  "Vesta_0.1.176_arm64.deb",
  "Vesta_0.1.176_x86_64.rpm",
  "Vesta_0.1.176_aarch64.rpm",
  "Vesta_0.1.176_universal.dmg",
].map(asset);

const FOREIGN_ARCH = ["Vesta_0.1.176_armv7l.deb"].map(asset);

describe("linux release asset selection", () => {
  it.each([
    { assets: RELEASE, arch: "arm64", ext: ".deb", expected: "Vesta_0.1.176_arm64.deb" },
    { assets: RELEASE, arch: "x64", ext: ".deb", expected: "Vesta_0.1.176_amd64.deb" },
    { assets: RELEASE, arch: "arm64", ext: ".rpm", expected: "Vesta_0.1.176_aarch64.rpm" },
    { assets: RELEASE, arch: "x64", ext: ".rpm", expected: "Vesta_0.1.176_x86_64.rpm" },
    { assets: RELEASE, arch: "x64", ext: ".AppImage", expected: undefined },
    { assets: FOREIGN_ARCH, arch: "arm64", ext: ".deb", expected: undefined },
  ])("$arch $ext -> $expected", ({ assets, arch, ext, expected }) => {
    expect(selectLinuxAsset(assets, arch, ext)?.name).toBe(expected);
  });
});

describe("latest-channel version comparison", () => {
  it.each([
    { candidate: "0.1.180", current: "0.1.179", expected: true },
    { candidate: "0.2.0", current: "0.1.179", expected: true },
    { candidate: "1.0.0", current: "0.9.9", expected: true },
    { candidate: "0.1.180-beta", current: "0.1.179", expected: true },
    { candidate: "0.1.179", current: "0.1.179", expected: false },
    { candidate: "0.1.178", current: "0.1.179", expected: false },
    { candidate: "0.1.9", current: "0.1.10", expected: false },
  ])(
    "$candidate newer than $current -> $expected",
    ({ candidate, current, expected }) => {
      expect(isNewerVersion(candidate, current)).toBe(expected);
    },
  );
});

describe("background auto-update errors", () => {
  it("attaches an error listener so a mid-download failure is consumed, not thrown", async () => {
    const platform = Object.getOwnPropertyDescriptor(process, "platform");
    // Force the electron-updater path (Linux uses the manual package path instead).
    Object.defineProperty(process, "platform", {
      value: "darwin",
      configurable: true,
    });
    try {
      await checkForAppUpdate();
      // Node throws on an "error" EventEmitter event with no listener; registering one turns a
      // mid-download failure into a logged no-op instead of an uncaught main-process exception.
      const errorHandler = updaterMock.handlers.error;
      expect(errorHandler).toBeDefined();
      expect(() => errorHandler?.(new Error("network blip"))).not.toThrow();
    } finally {
      if (platform) Object.defineProperty(process, "platform", platform);
    }
  });
});

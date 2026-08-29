import { EventEmitter } from "node:events";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  downloadAppUpdate,
  getAppUpdate,
  isNewerVersion,
  selectLinuxAsset,
} from "./updater";

// A stand-in for electron-updater's autoUpdater that lets a test steer the check result and
// records the handlers the code registers.
const updaterMock = vi.hoisted(() => {
  const handlers: Record<string, (arg: unknown) => void> = {};
  let checkResult: { updateInfo: { version: string } } | null = null;
  let checkError: Error | null = null;
  const autoUpdater = {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    allowDowngrade: true,
    on(event: string, cb: (arg: unknown) => void): void {
      handlers[event] = cb;
    },
    removeAllListeners(): void {
      /* noop */
    },
    setFeedURL(): void {
      /* noop */
    },
    checkForUpdates(): Promise<{ updateInfo: { version: string } } | null> {
      if (checkError) return Promise.reject(checkError);
      return Promise.resolve(checkResult);
    },
    downloadUpdate: (): Promise<string[]> => Promise.resolve([]),
    quitAndInstall(): void {
      /* noop */
    },
  };
  return {
    autoUpdater,
    handlers,
    reset(): void {
      checkResult = null;
      checkError = null;
      autoUpdater.allowDowngrade = true;
    },
    setCheckResult(version: string | null): void {
      checkError = null;
      checkResult = version ? { updateInfo: { version } } : null;
    },
    setCheckError(error: Error): void {
      checkError = error;
    },
  };
});

// Every spawned command (dpkg/rpm probes, pkexec) succeeds with no output.
const spawnMock = vi.hoisted(() => ({
  spawn: () => {
    const child = Object.assign(new EventEmitter(), {
      stderr: new EventEmitter(),
    });
    setImmediate(() => child.emit("close", 0));
    return child;
  },
}));

vi.mock("electron-updater", () => ({
  default: { autoUpdater: updaterMock.autoUpdater },
}));
vi.mock("electron", () => ({
  app: { getPath: () => "/tmp", getVersion: () => "0.1.0" },
}));
vi.mock("node:child_process", () => spawnMock);

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

const withPlatform = async (platform: string, fn: () => Promise<void>) => {
  const original = Object.getOwnPropertyDescriptor(process, "platform");
  Object.defineProperty(process, "platform", {
    value: platform,
    configurable: true,
  });
  try {
    await fn();
  } finally {
    if (original) Object.defineProperty(process, "platform", original);
  }
};

const fetchResponse = (body: unknown, ok = true) =>
  vi.fn(() =>
    Promise.resolve({
      ok,
      status: ok ? 200 : 404,
      json: () =>
        body instanceof Error ? Promise.reject(body) : Promise.resolve(body),
    }),
  );

beforeEach(() => {
  updaterMock.reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("linux release asset selection", () => {
  it.each([
    {
      assets: RELEASE,
      arch: "arm64",
      ext: ".deb",
      expected: "Vesta_0.1.176_arm64.deb",
    },
    {
      assets: RELEASE,
      arch: "x64",
      ext: ".deb",
      expected: "Vesta_0.1.176_amd64.deb",
    },
    {
      assets: RELEASE,
      arch: "arm64",
      ext: ".rpm",
      expected: "Vesta_0.1.176_aarch64.rpm",
    },
    {
      assets: RELEASE,
      arch: "x64",
      ext: ".rpm",
      expected: "Vesta_0.1.176_x86_64.rpm",
    },
    { assets: RELEASE, arch: "x64", ext: ".AppImage", expected: undefined },
    { assets: FOREIGN_ARCH, arch: "arm64", ext: ".deb", expected: undefined },
  ])("$arch $ext -> $expected", ({ assets, arch, ext, expected }) => {
    expect(selectLinuxAsset(assets, arch, ext)?.name).toBe(expected);
  });
});

describe("latest-channel version comparison", () => {
  it.each([
    { candidate: "0.1.180", current: "0.1.179", expected: true },
    { candidate: "0.1.179", current: "0.1.179", expected: false },
    // Numeric, not lexicographic: 0.1.9 is older than 0.1.10.
    { candidate: "0.1.9", current: "0.1.10", expected: false },
  ])(
    "$candidate newer than $current -> $expected",
    ({ candidate, current, expected }) => {
      expect(isNewerVersion(candidate, current)).toBe(expected);
    },
  );
});

describe("manual app-update check (darwin path)", () => {
  it("reports available with the version when the feed is newer", async () => {
    await withPlatform("darwin", async () => {
      updaterMock.setCheckResult("0.2.0");
      expect(await getAppUpdate()).toEqual({
        available: true,
        version: "0.2.0",
      });
    });
  });

  it("reports not-available when the feed is the same or older", async () => {
    await withPlatform("darwin", async () => {
      updaterMock.setCheckResult("0.1.0");
      expect(await getAppUpdate()).toEqual({ available: false, version: null });
    });
  });

  it("fails closed when the check throws", async () => {
    await withPlatform("darwin", async () => {
      updaterMock.setCheckError(new Error("network blip"));
      expect(await getAppUpdate()).toEqual({ available: false, version: null });
    });
  });

  it("configures the updater up-only", async () => {
    await withPlatform("darwin", async () => {
      updaterMock.setCheckResult("0.2.0");
      await getAppUpdate();
      expect(updaterMock.autoUpdater.allowDowngrade).toBe(false);
    });
  });
});

describe("manual app-update check (linux path)", () => {
  it("strips the tag's v prefix and reports the newer release", async () => {
    await withPlatform("linux", async () => {
      vi.stubGlobal("fetch", fetchResponse({ tag_name: "v0.2.0", assets: [] }));
      expect(await getAppUpdate()).toEqual({
        available: true,
        version: "0.2.0",
      });
    });
  });

  it.each<{ name: string; body: unknown; ok: boolean }>([
    { name: "the release lookup is not OK", body: {}, ok: false },
    {
      name: "the release body is malformed",
      body: { tag: "v0.2.0" },
      ok: true,
    },
    {
      name: "the release body is not JSON",
      body: new Error("bad json"),
      ok: true,
    },
  ])("fails closed when $name", async ({ body, ok }) => {
    await withPlatform("linux", async () => {
      vi.stubGlobal("fetch", fetchResponse(body, ok));
      expect(await getAppUpdate()).toEqual({ available: false, version: null });
    });
  });

  it("does not download when the latest release is not newer", async () => {
    await withPlatform("linux", async () => {
      const fetch = fetchResponse({ tag_name: "v0.1.0", assets: RELEASE });
      vi.stubGlobal("fetch", fetch);
      await downloadAppUpdate(() => undefined);
      expect(fetch).toHaveBeenCalledTimes(1);
    });
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { autoUpdater as squirrelMac } from "electron";
import {
  downloadAppUpdate,
  getAppUpdate,
  quitAndInstallUpdate,
} from "./updater";

interface CheckResult {
  isUpdateAvailable: boolean;
  updateInfo: { version: string };
}

// A stand-in for electron-updater's autoUpdater that lets a test steer the check result and
// records the handlers the code registers.
const updaterMock = vi.hoisted(() => {
  const handlers: Record<string, (arg: unknown) => void> = {};
  let checkResult: CheckResult | null = null;
  let checkError: Error | null = null;
  const autoUpdater = {
    autoDownload: true,
    autoInstallOnAppQuit: true,
    allowDowngrade: true,
    downloaded: 0,
    installed: 0,
    on(event: string, cb: (arg: unknown) => void): void {
      handlers[event] = cb;
    },
    removeAllListeners(): void {
      /* noop */
    },
    checkForUpdates(): Promise<CheckResult | null> {
      if (checkError) return Promise.reject(checkError);
      return Promise.resolve(checkResult);
    },
    downloadUpdate(): Promise<string[]> {
      autoUpdater.downloaded += 1;
      return Promise.resolve([]);
    },
    quitAndInstall(): void {
      autoUpdater.installed += 1;
    },
  };
  return {
    autoUpdater,
    handlers,
    reset(): void {
      checkResult = null;
      checkError = null;
      autoUpdater.allowDowngrade = true;
      autoUpdater.autoDownload = true;
      autoUpdater.autoInstallOnAppQuit = true;
      autoUpdater.downloaded = 0;
      autoUpdater.installed = 0;
    },
    setCheckResult(result: CheckResult | null): void {
      checkError = null;
      checkResult = result;
    },
    setCheckError(error: Error): void {
      checkError = error;
    },
  };
});

vi.mock("electron-updater", () => ({ autoUpdater: updaterMock.autoUpdater }));

// Electron's native autoUpdater, which on macOS is Squirrel.Mac.
vi.mock("electron", async () => ({
  autoUpdater: new (await import("node:events")).EventEmitter(),
}));

const realPlatform = process.platform;
function onPlatform(platform: NodeJS.Platform): void {
  Object.defineProperty(process, "platform", { value: platform });
}

beforeEach(() => {
  updaterMock.reset();
  squirrelMac.removeAllListeners();
  onPlatform("win32");
});

afterEach(() => {
  onPlatform(realPlatform);
});

describe("manual app-update check", () => {
  it("reports available with the version electron-updater resolved", async () => {
    updaterMock.setCheckResult({
      isUpdateAvailable: true,
      updateInfo: { version: "0.2.0" },
    });
    expect(await getAppUpdate()).toEqual({ available: true, version: "0.2.0" });
  });

  it("reports not-available when electron-updater finds nothing newer", async () => {
    updaterMock.setCheckResult({
      isUpdateAvailable: false,
      updateInfo: { version: "0.1.0" },
    });
    expect(await getAppUpdate()).toEqual({ available: false, version: null });
  });

  it("reports not-available when the check yields no result", async () => {
    updaterMock.setCheckResult(null);
    expect(await getAppUpdate()).toEqual({ available: false, version: null });
  });

  it("fails closed when the check throws", async () => {
    updaterMock.setCheckError(new Error("network blip"));
    expect(await getAppUpdate()).toEqual({ available: false, version: null });
  });

  it("configures the updater manual and up-only", async () => {
    updaterMock.setCheckResult(null);
    await getAppUpdate();
    expect(updaterMock.autoUpdater.allowDowngrade).toBe(false);
    expect(updaterMock.autoUpdater.autoDownload).toBe(false);
    expect(updaterMock.autoUpdater.autoInstallOnAppQuit).toBe(false);
  });

  // On macOS the flag only hands the download to Squirrel.Mac to stage; the install waits for the click.
  it("lets Squirrel.Mac stage the download on macOS", async () => {
    onPlatform("darwin");
    updaterMock.setCheckResult(null);
    await getAppUpdate();
    expect(updaterMock.autoUpdater.autoInstallOnAppQuit).toBe(true);
  });
});

describe("manual app-update download and install", () => {
  it("downloads once and relays progress as a percentage", async () => {
    updaterMock.setCheckResult({
      isUpdateAvailable: true,
      updateInfo: { version: "0.2.0" },
    });
    const seen: number[] = [];
    await downloadAppUpdate((percent) => seen.push(percent));
    updaterMock.handlers["download-progress"]?.({ percent: 42 });
    expect(updaterMock.autoUpdater.downloaded).toBe(1);
    expect(seen).toEqual([42]);
  });

  it("on macOS stays downloading until Squirrel.Mac has staged the update", async () => {
    onPlatform("darwin");
    let settled = false;
    const download = downloadAppUpdate(() => undefined).then(() => {
      settled = true;
    });
    await vi.waitFor(() => {
      expect(updaterMock.autoUpdater.downloaded).toBe(1);
    });
    expect(settled).toBe(false);
    squirrelMac.emit("update-downloaded");
    await download;
    expect(settled).toBe(true);
  });

  it("on macOS fails the download when Squirrel.Mac cannot stage it", async () => {
    onPlatform("darwin");
    const download = downloadAppUpdate(() => undefined);
    await vi.waitFor(() => {
      expect(updaterMock.autoUpdater.downloaded).toBe(1);
    });
    squirrelMac.emit("error", new Error("code signature mismatch"));
    await expect(download).rejects.toThrow("code signature mismatch");
  });

  it("hands the install to electron-updater", () => {
    quitAndInstallUpdate();
    expect(updaterMock.autoUpdater.installed).toBe(1);
  });
});

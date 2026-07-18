// Exercises localStorage and window, so it runs in the jsdom project
// (.test.tsx include) rather than the node one.
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConnectionConfig } from "@/lib/connection";
import { createBrowserBridge } from "./browser";
import { createElectronBridge } from "./electron";
import type { VestaNativeApi } from "./types";

const CONFIG: ConnectionConfig = {
  url: "https://box.example",
  accessToken: "at",
  refreshToken: "rt",
  expiresAt: 123,
};

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("browser bridge", () => {
  it("round-trips the connection through localStorage", async () => {
    const bridge = createBrowserBridge();
    await bridge.connectionStore.write(CONFIG);
    expect(await bridge.connectionStore.read()).toEqual(CONFIG);
    await bridge.connectionStore.clear();
    expect(await bridge.connectionStore.read()).toBeNull();
  });

  it("rejects a stored connection missing tokens", async () => {
    localStorage.setItem("vesta-connection", JSON.stringify({ url: "x" }));
    expect(await createBrowserBridge().connectionStore.read()).toBeNull();
  });

  it("accepts a hosted connection without a refresh token", async () => {
    const hosted: ConnectionConfig = {
      url: "https://box.example",
      accessToken: "at",
      refreshToken: "",
      expiresAt: 123,
      hosted: true,
    };
    const bridge = createBrowserBridge();
    await bridge.connectionStore.write(hosted);
    expect(await bridge.connectionStore.read()).toEqual(hosted);
  });

  it("opens external urls in a new tab", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    await createBrowserBridge().openExternal("https://vesta.run");
    expect(open).toHaveBeenCalledWith("https://vesta.run", "_blank");
  });

  it("has no oauth loopback", () => {
    expect(createBrowserBridge().oauthLoopback).toBeNull();
  });
});

describe("electron bridge", () => {
  function fakeApi(overrides: Partial<VestaNativeApi> = {}): VestaNativeApi {
    const noopUnsubscribe = () => {
      /* noop */
    };
    return {
      platform: "darwin",
      focusWindow: vi.fn(() => Promise.resolve()),
      setTheme: vi.fn(),
      openExternal: vi.fn(() => Promise.resolve()),
      storeRead: vi.fn(() => Promise.resolve(null)),
      storeWrite: vi.fn(() => Promise.resolve()),
      storeClear: vi.fn(() => Promise.resolve()),
      oauthStart: vi.fn(() => Promise.resolve(4242)),
      onOauthCallback: vi.fn(() => noopUnsubscribe),
      oauthCancel: vi.fn(() => Promise.resolve()),
      installUpdate: vi.fn(() => Promise.resolve()),
      onWindowFocus: vi.fn(() => noopUnsubscribe),
      windowMinimize: vi.fn(() => Promise.resolve()),
      windowToggleMaximize: vi.fn(() => Promise.resolve()),
      windowClose: vi.fn(() => Promise.resolve()),
      windowIsMaximized: vi.fn(() => Promise.resolve(false)),
      onWindowMaximizedChange: vi.fn(() => noopUnsubscribe),
      ...overrides,
    };
  }

  it("maps node platforms to app platforms", () => {
    expect(createElectronBridge(fakeApi()).platform).toBe("macos");
    expect(createElectronBridge(fakeApi({ platform: "win32" })).platform).toBe(
      "windows",
    );
    expect(createElectronBridge(fakeApi({ platform: "linux" })).platform).toBe(
      "linux",
    );
  });

  it("validates the stored connection shape", async () => {
    const api = fakeApi({
      storeRead: vi.fn(() => Promise.resolve({ url: "only-url" })),
    });
    expect(await createElectronBridge(api).connectionStore.read()).toBeNull();
    const good = fakeApi({ storeRead: vi.fn(() => Promise.resolve(CONFIG)) });
    expect(await createElectronBridge(good).connectionStore.read()).toEqual(
      CONFIG,
    );
  });

  it("exposes the oauth loopback", async () => {
    const bridge = createElectronBridge(fakeApi());
    expect(await bridge.oauthLoopback?.start()).toBe(4242);
  });

  it("routes theme, focus, and update calls to the preload api", async () => {
    const setTheme = vi.fn();
    const focusWindow = vi.fn(() => Promise.resolve());
    const installUpdate = vi.fn(() => Promise.resolve());
    const bridge = createElectronBridge(
      fakeApi({ setTheme, focusWindow, installUpdate }),
    );
    bridge.setNativeTheme("dark");
    await bridge.focusWindow();
    await bridge.installAppUpdate("0.1.176");
    expect(setTheme).toHaveBeenCalledWith("dark");
    expect(focusWindow).toHaveBeenCalled();
    expect(installUpdate).toHaveBeenCalledWith("0.1.176");
  });
});

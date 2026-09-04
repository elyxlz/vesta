// Exercises localStorage and window, so it runs in the jsdom project
// (.test.tsx include) rather than the node one.
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConnectionConfig } from "@/lib/connection";
import { createBrowserBridge } from "./browser";
import { createElectronBridge } from "./electron";
import { selectNativeBridge } from "./index";
import type { VestaNativeApi } from "./types";

const CONFIG: ConnectionConfig = {
  url: "https://box.example",
  accessToken: "at",
  refreshToken: "rt",
  expiresAt: 123,
};

// `satisfies` so a preload field added to the contract fails to compile here
// until the fake grows with it.
function fakeApi(overrides: Partial<VestaNativeApi> = {}): VestaNativeApi {
  const noopUnsubscribe = () => {
    /* noop */
  };
  const base = {
    platform: "darwin",
    focusWindow: vi.fn(() => Promise.resolve()),
    setTheme: vi.fn(),
    openExternal: vi.fn(() => Promise.resolve()),
    getAppUpdate: vi.fn(() => Promise.resolve<unknown>(null)),
    downloadAppUpdate: vi.fn(() => Promise.resolve()),
    onAppUpdateProgress: vi.fn(() => noopUnsubscribe),
    installAppUpdate: vi.fn(() => Promise.resolve()),
    storeRead: vi.fn(() => Promise.resolve(null)),
    storeWrite: vi.fn(() => Promise.resolve()),
    storeClear: vi.fn(() => Promise.resolve()),
    storeIsSecure: vi.fn(() => Promise.resolve(true)),
    recentStoreRead: vi.fn(() => Promise.resolve(null)),
    recentStoreWrite: vi.fn(() => Promise.resolve()),
    recentStoreClear: vi.fn(() => Promise.resolve()),
    oauthStart: vi.fn(() => Promise.resolve(4242)),
    onOauthCallback: vi.fn(() => noopUnsubscribe),
    oauthCancel: vi.fn(() => Promise.resolve()),
    readGeolocation: vi.fn(() => Promise.resolve<unknown>(null)),
    onWindowFocus: vi.fn(() => noopUnsubscribe),
    windowMinimize: vi.fn(() => Promise.resolve()),
    windowToggleMaximize: vi.fn(() => Promise.resolve()),
    windowClose: vi.fn(() => Promise.resolve()),
    windowIsMaximized: vi.fn(() => Promise.resolve(false)),
    onWindowMaximizedChange: vi.fn(() => noopUnsubscribe),
    getOpenAtLogin: vi.fn(() => Promise.resolve(false)),
    setOpenAtLogin: vi.fn(() => Promise.resolve()),
  } satisfies VestaNativeApi;
  return { ...base, ...overrides };
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("selectNativeBridge", () => {
  it("uses the electron bridge when the preload injected the api", () => {
    const bridge = selectNativeBridge({
      vestaNative: fakeApi(),
      location: { protocol: "vesta:" },
    });
    expect(bridge.runtime).toBe("electron");
  });

  it("uses the browser bridge in a normal browser tab", () => {
    const bridge = selectNativeBridge({ location: { protocol: "https:" } });
    expect(bridge.runtime).toBe("browser");
  });

  it("throws inside the desktop shell when the preload bridge is missing", () => {
    expect(() =>
      selectNativeBridge({ location: { protocol: "vesta:" } }),
    ).toThrow(/preload/i);
  });
});

describe("browser bridge", () => {
  it("round-trips the connection through localStorage", async () => {
    const bridge = createBrowserBridge();
    await bridge.connectionStore.write(CONFIG);
    expect(await bridge.connectionStore.read()).toEqual(CONFIG);
    await bridge.connectionStore.clear();
    expect(await bridge.connectionStore.read()).toBeNull();
  });

  it("round-trips recent gateways through localStorage", async () => {
    const bridge = createBrowserBridge();
    const gateways = [{ connection: CONFIG, lastConnectedAt: 1 }];
    await bridge.recentGatewayStore.write(gateways);
    expect(await bridge.recentGatewayStore.read()).toEqual(gateways);
    await bridge.recentGatewayStore.clear();
    expect(await bridge.recentGatewayStore.read()).toBeNull();
  });

  it("rejects a stored connection missing tokens", async () => {
    localStorage.setItem("vesta-connection", JSON.stringify({ url: "x" }));
    expect(await createBrowserBridge().connectionStore.read()).toBeNull();
  });

  it("rejects a stored connection whose url is not an http origin", async () => {
    localStorage.setItem(
      "vesta-connection",
      JSON.stringify({ ...CONFIG, url: "javascript:alert(1)" }),
    );
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
});

describe("electron bridge", () => {
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

  it("migrates plaintext renderer gateway records to the native store", async () => {
    const gateways = [{ connection: CONFIG, lastConnectedAt: 1 }];
    localStorage.setItem("vesta-recent-gateways", JSON.stringify(gateways));
    const recentStoreWrite = vi.fn(() => Promise.resolve());
    const bridge = createElectronBridge(
      fakeApi({
        recentStoreRead: vi.fn(() => Promise.resolve(null)),
        recentStoreWrite,
      }),
    );

    expect(await bridge.recentGatewayStore.read()).toEqual(gateways);
    expect(recentStoreWrite).toHaveBeenCalledWith(gateways);
    expect(localStorage.getItem("vesta-recent-gateways")).toBeNull();
  });

  it("parses the native geolocation answer at the boundary", async () => {
    const good = fakeApi({
      readGeolocation: vi.fn(() =>
        Promise.resolve<unknown>({
          latitude: 39.2238,
          longitude: 9.1217,
          accuracyM: 25,
        }),
      ),
    });
    expect(await createElectronBridge(good).readGeolocation?.()).toEqual({
      latitude: 39.2238,
      longitude: 9.1217,
      accuracyM: 25,
    });
    const malformed = fakeApi({
      readGeolocation: vi.fn(() =>
        Promise.resolve<unknown>({ latitude: "39", longitude: 9 }),
      ),
    });
    expect(
      await createElectronBridge(malformed).readGeolocation?.(),
    ).toBeNull();
    expect(
      await createElectronBridge(fakeApi()).readGeolocation?.(),
    ).toBeNull();
  });

  it.each<[string, unknown, { available: boolean; version: string | null }]>([
    [
      "an available release carries its version",
      { available: true, version: "0.3.0" },
      { available: true, version: "0.3.0" },
    ],
    [
      "an available answer with no version is still an update",
      { available: true },
      { available: true, version: null },
    ],
    [
      "a not-available answer drops any version",
      { available: false, version: "0.3.0" },
      { available: false, version: null },
    ],
    [
      "a malformed answer reads as no update",
      "nope",
      {
        available: false,
        version: null,
      },
    ],
  ])("parses the app update answer: %s", async (_name, answer, expected) => {
    const api = fakeApi({
      getAppUpdate: vi.fn(() => Promise.resolve<unknown>(answer)),
    });
    expect(await createElectronBridge(api).appUpdate?.check()).toEqual(
      expected,
    );
  });

  it("unsubscribes from download progress even when the download throws", async () => {
    const unsubscribe = vi.fn();
    const api = fakeApi({
      onAppUpdateProgress: vi.fn(() => unsubscribe),
      downloadAppUpdate: vi.fn(() => Promise.reject(new Error("offline"))),
    });
    await expect(
      createElectronBridge(api).appUpdate?.download(() => undefined),
    ).rejects.toThrow("offline");
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });
});

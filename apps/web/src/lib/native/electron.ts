// Counterpart of the VestaNativeApi contract implemented by
// apps/desktop/src/preload.ts, keep the two declarations identical.
import type { Platform } from "@/lib/platform";
import { parseConnectionConfig } from "./parse-connection-config";
import type {
  NativeBridge,
  NativeGeolocationFix,
  VestaNativeApi,
} from "./types";

const NODE_PLATFORM_MAP: Record<string, Platform> = {
  darwin: "macos",
  win32: "windows",
  linux: "linux",
};

// Parse at the boundary: the preload answer is untyped IPC, so validate the shape here.
export function parseNativeFix(value: unknown): NativeGeolocationFix | null {
  if (typeof value !== "object" || value === null) return null;
  const fix = value as Record<string, unknown>;
  const { latitude, longitude, accuracyM } = fix;
  if (typeof latitude !== "number" || !Number.isFinite(latitude)) return null;
  if (typeof longitude !== "number" || !Number.isFinite(longitude)) return null;
  return {
    latitude,
    longitude,
    accuracyM:
      typeof accuracyM === "number" && Number.isFinite(accuracyM)
        ? accuracyM
        : null,
  };
}

export function createElectronBridge(api: VestaNativeApi): NativeBridge {
  const platform = NODE_PLATFORM_MAP[api.platform] ?? "linux";
  return {
    runtime: "electron",
    platform,
    connectionStore: {
      async read() {
        return parseConnectionConfig(await api.storeRead());
      },
      async write(config) {
        await api.storeWrite(config);
      },
      async clear() {
        await api.storeClear();
      },
    },
    openExternal: (url) => api.openExternal(url),
    focusWindow: () => api.focusWindow(),
    setNativeTheme: (theme) => api.setTheme(theme),
    onWindowFocusChange: (cb) => api.onWindowFocus(cb),
    oauthLoopback: {
      start: () => api.oauthStart(),
      onCallback: (cb) => api.onOauthCallback(cb),
      cancel: (port) => api.oauthCancel(port),
    },
    readGeolocation: async () => parseNativeFix(await api.readGeolocation()),
    // macOS keeps its native traffic lights; only Windows draws custom controls.
    windowControls:
      platform === "windows"
        ? {
            minimize: () => api.windowMinimize(),
            toggleMaximize: () => api.windowToggleMaximize(),
            close: () => api.windowClose(),
            isMaximized: () => api.windowIsMaximized(),
            onMaximizedChange: (cb) => api.onWindowMaximizedChange(cb),
          }
        : null,
  };
}

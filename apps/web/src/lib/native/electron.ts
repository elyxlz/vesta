// Counterpart of the VestaNativeApi contract implemented by
// apps/desktop/src/preload.ts, keep the two declarations identical.
import type { Platform } from "@/lib/platform";
import { parseConnectionConfig } from "./parse-connection-config";
import type {
  AppUpdateStatus,
  NativeBridge,
  NativeGeolocationFix,
  VestaNativeApi,
} from "./types";

const NODE_PLATFORM_MAP: Record<string, Platform> = {
  darwin: "macos",
  win32: "windows",
  linux: "linux",
};
const LEGACY_RECENT_GATEWAYS_KEY = "vesta-recent-gateways";

function readLegacyRecentGateways(): unknown {
  const raw = localStorage.getItem(LEGACY_RECENT_GATEWAYS_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    localStorage.removeItem(LEGACY_RECENT_GATEWAYS_KEY);
    return null;
  }
}

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

// Parse at the boundary: the preload answer is untyped IPC, so validate the shape here.
export function parseAppUpdateStatus(value: unknown): AppUpdateStatus {
  if (typeof value !== "object" || value === null)
    return { available: false, version: null };
  const status = value as Record<string, unknown>;
  const available = status.available === true;
  const version = typeof status.version === "string" ? status.version : null;
  return { available, version: available ? version : null };
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
    recentGatewayStore: {
      async read() {
        const stored = await api.recentStoreRead();
        if (stored !== null) return stored;
        // LEGACY(remove-when: MIN_SUPPORTED_CLIENT_VERSION exceeds 0.2.13):
        // Move renderer records into the encrypted main-process store.
        const legacy = readLegacyRecentGateways();
        if (legacy === null) return null;
        await api.recentStoreWrite(legacy);
        localStorage.removeItem(LEGACY_RECENT_GATEWAYS_KEY);
        return legacy;
      },
      write: (value) => api.recentStoreWrite(value),
      clear: () => api.recentStoreClear(),
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
    appUpdate: {
      check: async () => parseAppUpdateStatus(await api.getAppUpdate()),
      download: async (onProgress) => {
        const unsubscribe = api.onAppUpdateProgress(onProgress);
        try {
          await api.downloadAppUpdate();
        } finally {
          unsubscribe();
        }
      },
      install: () => api.installAppUpdate(),
    },
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

// Counterpart of the VestaNativeApi contract implemented by
// apps/desktop/src/preload.ts, keep the two declarations identical.
import type { ConnectionConfig } from "@/lib/connection";
import type { Platform } from "@/lib/platform";
import type { NativeBridge, VestaNativeApi } from "./types";

const NODE_PLATFORM_MAP: Record<string, Platform> = {
  darwin: "macos",
  win32: "windows",
  linux: "linux",
};

function isConnectionConfig(value: unknown): value is ConnectionConfig {
  if (value === null || typeof value !== "object") return false;
  const config = value as ConnectionConfig;
  return Boolean(
    config.url && config.accessToken && (config.refreshToken || config.hosted),
  );
}

export function createElectronBridge(api: VestaNativeApi): NativeBridge {
  return {
    runtime: "electron",
    platform: NODE_PLATFORM_MAP[api.platform] ?? "linux",
    connectionStore: {
      async read() {
        const value = await api.storeRead();
        return isConnectionConfig(value) ? value : null;
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
    installAppUpdate: (version) => api.installUpdate(version),
  };
}

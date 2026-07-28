// Counterpart of the VestaNativeApi contract implemented by
// apps/desktop/src/preload.ts, keep the two declarations identical.
import type { Platform } from "@/lib/platform";
import { parseConnectionConfig } from "./parse-connection-config";
import type { NativeBridge, VestaNativeApi } from "./types";

const NODE_PLATFORM_MAP: Record<string, Platform> = {
  darwin: "macos",
  win32: "windows",
  linux: "linux",
};

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

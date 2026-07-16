import type { ConnectionConfig } from "@/lib/connection";
import { detectPlatform } from "@/lib/platform";
import type { NativeBridge } from "./types";

const STORAGE_KEY = "vesta-connection";

export function parseConnection(raw: string): ConnectionConfig | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object") return null;
    const config = parsed as ConnectionConfig;
    if (
      config.url &&
      config.accessToken &&
      (config.refreshToken || config.hosted)
    ) {
      return config;
    }
    return null;
  } catch {
    return null;
  }
}

export function createBrowserBridge(): NativeBridge {
  return {
    runtime: "browser",
    platform: detectPlatform(),
    connectionStore: {
      read() {
        const raw = localStorage.getItem(STORAGE_KEY);
        return Promise.resolve(raw ? parseConnection(raw) : null);
      },
      write(config) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
        return Promise.resolve();
      },
      clear() {
        localStorage.removeItem(STORAGE_KEY);
        return Promise.resolve();
      },
    },
    openExternal(url) {
      window.open(url, "_blank");
      return Promise.resolve();
    },
    focusWindow() {
      window.focus();
      return Promise.resolve();
    },
    setNativeTheme() {
      /* noop: the browser follows the OS theme */
    },
    onWindowFocusChange() {
      return () => {
        /* noop: nothing to unsubscribe */
      };
    },
    oauthLoopback: null,
    windowControls: null,
    installAppUpdate() {
      window.location.reload();
      return Promise.resolve();
    },
  };
}

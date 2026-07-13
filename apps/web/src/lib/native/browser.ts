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
      async read() {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? parseConnection(raw) : null;
      },
      async write(config) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
      },
      async clear() {
        localStorage.removeItem(STORAGE_KEY);
      },
    },
    async openExternal(url) {
      window.open(url, "_blank");
    },
    async focusWindow() {
      window.focus();
    },
    setNativeTheme() {},
    onWindowFocusChange() {
      return () => {};
    },
    oauthLoopback: null,
    windowControls: null,
    async installAppUpdate() {
      window.location.reload();
    },
  };
}

import type { ConnectionConfig } from "@/lib/connection";
import { detectPlatform } from "@/lib/platform";
import { parseConnectionConfig } from "./parse-connection-config";
import type { NativeBridge } from "./types";

const STORAGE_KEY = "vesta-connection";

export function parseConnection(raw: string): ConnectionConfig | null {
  try {
    return parseConnectionConfig(JSON.parse(raw));
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
    readGeolocation: null,
    appUpdate: null,
  };
}

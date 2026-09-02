import type { ConnectionConfig } from "@/lib/connection";
import { detectPlatform } from "@/lib/platform";
import { parseConnectionConfig } from "./parse-connection-config";
import type { NativeBridge } from "./types";

const STORAGE_KEY = "vesta-connection";
const RECENT_GATEWAYS_STORAGE_KEY = "vesta-recent-gateways";

function readStoredJson(key: string): unknown {
  const raw = localStorage.getItem(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    localStorage.removeItem(key);
    return null;
  }
}

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
    recentGatewayStore: {
      read() {
        return Promise.resolve(readStoredJson(RECENT_GATEWAYS_STORAGE_KEY));
      },
      write(value) {
        localStorage.setItem(
          RECENT_GATEWAYS_STORAGE_KEY,
          JSON.stringify(value),
        );
        return Promise.resolve();
      },
      clear() {
        localStorage.removeItem(RECENT_GATEWAYS_STORAGE_KEY);
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
    credentialStorageIsSecure: null,
    appUpdate: null,
    loginItem: null,
  };
}

import { createBrowserBridge } from "./browser";
import { createElectronBridge } from "./electron";
import type { NativeBridge, Runtime, VestaNativeApi } from "./types";
import type { Platform } from "@/lib/platform";

export type { NativeBridge, NativeGeolocationFix } from "./types";

// The desktop shell serves the bundle on its own scheme (apps/desktop/src/window.ts); nothing
// else does. So a missing vestaNative there means the preload failed to inject the bridge, and
// falling back to the browser bridge would silently render the web app inside the desktop window.
// Throw instead, so that failure is loud and never ships.
const DESKTOP_SHELL_PROTOCOL = "vesta:";

interface ShellEnv {
  vestaNative?: VestaNativeApi;
  location: { protocol: string };
}

export function selectNativeBridge(env: ShellEnv | undefined): NativeBridge {
  if (env?.vestaNative) return createElectronBridge(env.vestaNative);
  if (env?.location.protocol === DESKTOP_SHELL_PROTOCOL)
    throw new Error(
      "desktop preload bridge missing: window.vestaNative was not injected",
    );
  return createBrowserBridge();
}

export const native: NativeBridge = selectNativeBridge(
  typeof window === "undefined" ? undefined : window,
);

export interface RuntimeInfo {
  runtime: Runtime;
  platform: Platform;
  /** Running inside the Electron desktop app. */
  isDesktopApp: boolean;
  /** Desktop OS (any runtime). */
  isDesktop: boolean;
  /** Phone (browser) platform. */
  isMobile: boolean;
  isMacOS: boolean;
  isWindows: boolean;
  isLinux: boolean;
  isIOS: boolean;
  isAndroid: boolean;
  vibrancy: boolean;
}

const isDesktopApp = native.runtime === "electron";
const { platform } = native;

export const runtimeInfo: RuntimeInfo = {
  runtime: native.runtime,
  platform,
  isDesktopApp,
  isDesktop:
    platform === "macos" || platform === "windows" || platform === "linux",
  isMobile: platform === "ios" || platform === "android",
  isMacOS: platform === "macos",
  isWindows: platform === "windows",
  isLinux: platform === "linux",
  isIOS: platform === "ios",
  isAndroid: platform === "android",
  vibrancy: isDesktopApp && (platform === "macos" || platform === "windows"),
};

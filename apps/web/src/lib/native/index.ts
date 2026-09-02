import { createBrowserBridge } from "./browser";
import { createElectronBridge } from "./electron";
import type { NativeBridge, Runtime } from "./types";
import type { Platform } from "@/lib/platform";

export type { NativeBridge, NativeGeolocationFix } from "./types";

export const native: NativeBridge =
  typeof window !== "undefined" && window.vestaNative
    ? createElectronBridge(window.vestaNative)
    : createBrowserBridge();

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

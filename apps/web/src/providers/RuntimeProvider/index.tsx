import { native } from "@/lib/native";
import type { Runtime } from "@/lib/native";
import type { Platform } from "@/lib/platform";

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

const { runtime, platform } = native;
const isDesktopApp = runtime === "electron";

const info: RuntimeInfo = {
  runtime,
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

export function useRuntime(): RuntimeInfo {
  return info;
}

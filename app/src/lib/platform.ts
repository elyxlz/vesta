import { buildPlatform } from "./env";

export type Platform = "macos" | "windows" | "linux" | "ios" | "android";

const TAURI_PLATFORM_MAP: Record<string, Platform> = {
  macos: "macos",
  darwin: "macos",
  windows: "windows",
  linux: "linux",
  ios: "ios",
  android: "android",
};

export function detectPlatform(): Platform {
  if (buildPlatform && buildPlatform in TAURI_PLATFORM_MAP) {
    return TAURI_PLATFORM_MAP[buildPlatform];
  }

  const ua = navigator.userAgent;
  if (ua.includes("Android")) return "android";
  if (ua.includes("iPhone") || ua.includes("iPad")) return "ios";
  if (ua.includes("Mac")) {
    if ("maxTouchPoints" in navigator && navigator.maxTouchPoints > 0)
      return "ios";
    return "macos";
  }
  if (ua.includes("Windows")) return "windows";
  return "linux";
}

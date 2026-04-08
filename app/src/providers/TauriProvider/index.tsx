import type { ReactNode } from "react";
import { isTauri } from "@/lib/env";
import { detectPlatform, type Platform } from "@/lib/platform";

export interface TauriInfo {
  isTauri: boolean;
  platform: Platform;
  isDesktop: boolean;
  isMobile: boolean;
  isMacOS: boolean;
  isWindows: boolean;
  isLinux: boolean;
  isIOS: boolean;
  isAndroid: boolean;
}

const platform = detectPlatform();

const info: TauriInfo = {
  isTauri,
  platform,
  isDesktop: platform === "macos" || platform === "windows" || platform === "linux",
  isMobile: platform === "ios" || platform === "android",
  isMacOS: platform === "macos",
  isWindows: platform === "windows",
  isLinux: platform === "linux",
  isIOS: platform === "ios",
  isAndroid: platform === "android",
};

export function TauriProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

export function useTauri(): TauriInfo {
  return info;
}

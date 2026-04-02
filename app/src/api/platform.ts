import { isTauri } from "@/lib/env";
import type { PlatformStatus } from "@/lib/types";

const WEB_PLATFORM_STATUS: PlatformStatus = {
  ready: true,
  platform: "web",
  wsl_installed: false,
  virtualization_enabled: null,
  distro_registered: false,
  distro_healthy: false,
  services_ready: false,
  needs_reboot: false,
  message: "",
};

export async function autoSetup(): Promise<boolean> {
  if (!isTauri) return true;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke("auto_setup");
}

export async function checkPlatform(): Promise<PlatformStatus> {
  if (!isTauri) return WEB_PLATFORM_STATUS;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke("platform_check");
}

export async function setupPlatform(): Promise<PlatformStatus> {
  if (!isTauri) return WEB_PLATFORM_STATUS;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke("platform_setup");
}

export async function runInstallScript(version: string): Promise<void> {
  if (!isTauri) return;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke("run_install_script", { version });
}

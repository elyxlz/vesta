import { isTauri } from "@/lib/env";
import { compareVersions } from "@/lib/version";

export function isNewer(latest: string, current: string): boolean {
  return compareVersions(latest, current) > 0;
}

export type UpdateInfo = {
  version: string;
  /** Update was downloaded and installed — app needs restart to apply. */
  installed: boolean;
};

export async function checkAndInstallUpdate(): Promise<UpdateInfo | null> {
  if (!isTauri) return null;
  try {
    const { getVersion } = await import("@tauri-apps/api/app");
    const { detectPlatform } = await import("@/lib/platform");
    if (detectPlatform() === "linux") {
      const current = await getVersion();
      const resp = await fetch(
        "https://api.github.com/repos/elyxlz/vesta/releases/latest",
      );
      if (!resp.ok) return null;
      const data = await resp.json();
      const latest = (data.tag_name as string).replace(/^v/, "");
      if (!isNewer(latest, current)) return null;
      return { version: latest, installed: false };
    }
    const { check } = await import("@tauri-apps/plugin-updater");
    const update = await check();
    if (!update) return null;
    await update.downloadAndInstall();
    return { version: update.version, installed: true };
  } catch (e) {
    console.error("Update check failed:", e);
    return null;
  }
}

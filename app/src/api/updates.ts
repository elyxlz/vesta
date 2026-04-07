import { isTauri } from "@/lib/env";

export function isNewer(latest: string, current: string): boolean {
  const a = latest.split(".").map(Number);
  const b = current.split(".").map(Number);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] ?? 0) > (b[i] ?? 0)) return true;
    if ((a[i] ?? 0) < (b[i] ?? 0)) return false;
  }
  return false;
}

export type UpdateInfo = {
  version: string;
  /** Update was downloaded and installed — app needs restart to apply. */
  installed: boolean;
  /** URL to download the update manually (Linux). */
  releaseUrl: string | null;
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
      const tag = data.tag_name as string;
      const latest = tag.replace(/^v/, "");
      if (!isNewer(latest, current)) return null;
      return {
        version: latest,
        installed: false,
        releaseUrl: data.html_url as string,
      };
    }
    const { check } = await import("@tauri-apps/plugin-updater");
    const update = await check();
    if (!update) return null;
    await update.downloadAndInstall();
    return { version: update.version, installed: true, releaseUrl: null };
  } catch (e) {
    console.error("Update check failed:", e);
    return null;
  }
}

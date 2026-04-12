import { isTauri } from "@/lib/env";

export async function openExternalUrl(url: string): Promise<void> {
  if (isTauri) {
    try {
      const { openUrl } = await import("@tauri-apps/plugin-opener");
      await openUrl(url);
      return;
    } catch { /* tauri not available */ }
  }

  window.open(url, "_blank");
}

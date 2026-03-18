import { getVersion } from "@tauri-apps/api/app";

export const appVersion: Promise<string> = getVersion();

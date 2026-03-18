import { invoke, Channel } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { check } from "@tauri-apps/plugin-updater";
import type { BoxInfo, ListEntry, LogEvent, PlatformStatus } from "./types";

export async function listBoxes(): Promise<ListEntry[]> {
  return invoke("list_agents");
}

export async function boxStatus(name: string): Promise<BoxInfo> {
  return invoke("agent_status", { name });
}

export async function createBox(name: string): Promise<void> {
  return invoke("create_agent", { name });
}

export async function startBox(name: string): Promise<void> {
  return invoke("start_agent", { name });
}

export async function stopBox(name: string): Promise<void> {
  return invoke("stop_agent", { name });
}

export async function restartBox(name: string): Promise<void> {
  return invoke("restart_agent", { name });
}

export async function deleteBox(name: string): Promise<void> {
  return invoke("delete_agent", { name });
}

export async function backupBox(name: string, output: string): Promise<void> {
  return invoke("backup_agent", { name, output });
}

export async function restoreBox(input: string, name?: string, replace?: boolean): Promise<void> {
  return invoke("restore_agent", { input, name: name ?? null, replace: replace ?? false });
}

export async function waitForReady(name: string, timeout?: number): Promise<void> {
  return invoke("wait_for_ready", { name, timeout: timeout ?? 30 });
}

export function streamLogs(
  name: string,
  onEvent: (event: LogEvent) => void,
): Promise<void> {
  const channel = new Channel<LogEvent>();
  channel.onmessage = onEvent;
  return invoke("stream_logs", { name, onEvent: channel });
}

export async function stopLogs(name: string): Promise<void> {
  return invoke("stop_logs", { name });
}

export async function authenticate(name: string): Promise<void> {
  return invoke("authenticate", { name });
}

export async function submitAuthCode(code: string): Promise<void> {
  return invoke("submit_auth_code", { code });
}

export async function boxHost(): Promise<string> {
  return invoke("agent_host");
}

export async function checkPlatform(): Promise<PlatformStatus> {
  return invoke("platform_check");
}

export async function setupPlatform(): Promise<PlatformStatus> {
  return invoke("platform_setup");
}

export async function getOs(): Promise<string> {
  return invoke("get_os");
}

export async function runInstallScript(version: string): Promise<void> {
  return invoke("run_install_script", { version });
}

export async function checkAndInstallUpdate(): Promise<{ version: string; installing: boolean } | null> {
  try {
    const os = await getOs();
    if (os === "linux") {
      const current = await getVersion();
      const resp = await fetch("https://api.github.com/repos/elyxlz/vesta/releases/latest");
      if (!resp.ok) return null;
      const data = await resp.json();
      const latest = (data.tag_name as string).replace(/^v/, "");
      if (latest === current) return null;
      return { version: latest, installing: false };
    }
    const update = await check();
    if (!update) return null;
    await update.downloadAndInstall();
    return { version: update.version, installing: true };
  } catch (e) {
    console.error("Update check failed:", e);
    return null;
  }
}

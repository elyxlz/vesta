import { invoke, Channel } from "@tauri-apps/api/core";
import type { AgentInfo, ListEntry, LogEvent, PlatformStatus } from "./types";

export async function listAgents(): Promise<ListEntry[]> {
  return invoke("list_agents");
}

export async function agentStatus(name: string): Promise<AgentInfo> {
  return invoke("agent_status", { name });
}

export async function createAgent(name: string): Promise<void> {
  return invoke("create_agent", { name });
}

export async function startAgent(name: string): Promise<void> {
  return invoke("start_agent", { name });
}

export async function stopAgent(name: string): Promise<void> {
  return invoke("stop_agent", { name });
}

export async function restartAgent(name: string): Promise<void> {
  return invoke("restart_agent", { name });
}

export async function deleteAgent(name: string): Promise<void> {
  return invoke("delete_agent", { name });
}

export async function backupAgent(name: string, output: string): Promise<void> {
  return invoke("backup_agent", { name, output });
}

export async function restoreAgent(input: string, name?: string, replace?: boolean): Promise<void> {
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

export async function agentHost(): Promise<string> {
  return invoke("agent_host");
}

export async function checkPlatform(): Promise<PlatformStatus> {
  return invoke("platform_check");
}

export async function setupPlatform(): Promise<PlatformStatus> {
  return invoke("platform_setup");
}

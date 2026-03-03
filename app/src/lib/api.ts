import { invoke, Channel } from "@tauri-apps/api/core";
import type { AgentInfo, LogEvent } from "./types";

export async function agentStatus(): Promise<AgentInfo> {
  return invoke("agent_status");
}

export async function createAgent(name?: string): Promise<void> {
  return invoke("create_agent", { name: name ?? null });
}

export async function startAgent(): Promise<void> {
  return invoke("start_agent");
}

export async function stopAgent(): Promise<void> {
  return invoke("stop_agent");
}

export async function restartAgent(): Promise<void> {
  return invoke("restart_agent");
}

export async function deleteAgent(): Promise<void> {
  return invoke("delete_agent");
}

export async function setAgentName(name: string): Promise<void> {
  return invoke("set_agent_name", { name });
}

export function streamLogs(
  onEvent: (event: LogEvent) => void,
): Promise<void> {
  const channel = new Channel<LogEvent>();
  channel.onmessage = onEvent;
  return invoke("stream_logs", { onEvent: channel });
}

export async function stopLogs(): Promise<void> {
  return invoke("stop_logs");
}

export async function authenticate(): Promise<void> {
  return invoke("authenticate");
}

export async function agentHost(): Promise<string> {
  return invoke("agent_host");
}

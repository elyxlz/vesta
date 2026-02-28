import { invoke, Channel } from "@tauri-apps/api/core";
import type { AgentInfo, ChatEvent, LogEvent } from "./types";

export async function agentExists(): Promise<boolean> {
  return invoke("agent_exists");
}

export async function agentStatus(): Promise<AgentInfo> {
  return invoke("agent_status");
}

export async function createAgent(): Promise<void> {
  return invoke("create_agent");
}

export async function startAgent(): Promise<void> {
  return invoke("start_agent");
}

export async function stopAgent(): Promise<void> {
  return invoke("stop_agent");
}

export async function deleteAgent(): Promise<void> {
  return invoke("delete_agent");
}

export function attachChat(
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const channel = new Channel<ChatEvent>();
  channel.onmessage = onEvent;
  return invoke("attach_chat", { onEvent: channel });
}

export async function sendMessage(message: string): Promise<void> {
  return invoke("send_message", { message });
}

export async function detachChat(): Promise<void> {
  return invoke("detach_chat");
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

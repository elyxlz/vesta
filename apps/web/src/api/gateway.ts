import { getConnection } from "@/lib/connection";
import type { ReleaseChannel, SseHandle } from "@vesta/core";
import type { LogEvent } from "@/lib/types";
import { apiJson } from "./client";
import { openLogStream } from "./log-stream";

let gatewayLogSource: SseHandle | null = null;

export function streamGatewayLogs(
  follow: boolean,
  onEvent: (event: LogEvent) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const conn = getConnection();
    if (!conn) {
      reject(new Error("not connected"));
      return;
    }

    const params = new URLSearchParams({ token: conn.accessToken });
    if (follow) params.set("follow", "true");
    const url = `${conn.url}/gateway/logs?${params.toString()}`;

    gatewayLogSource?.cancel();
    gatewayLogSource = openLogStream(url, "gateway_stopped", onEvent, () => {
      gatewayLogSource = null;
      resolve();
    });
  });
}

export function stopGatewayLogs(): void {
  if (gatewayLogSource) {
    gatewayLogSource.cancel();
    gatewayLogSource = null;
  }
}

export interface GatewayLan {
  exposed: boolean;
  url: string | null;
}

export interface GatewayInfo {
  lan: GatewayLan;
  tunnel_url: string | null;
  port: number;
}

export interface GatewayRetention {
  daily: number;
  weekly: number;
  monthly: number;
}

export interface GatewayAutoBackup {
  enabled: boolean;
  hour: number;
  retention: GatewayRetention;
}

export interface GatewaySettings {
  auto_update: boolean;
  channel: ReleaseChannel;
  auto_backup: GatewayAutoBackup;
}

export async function fetchGatewayInfo(): Promise<GatewayInfo> {
  return apiJson<GatewayInfo>("/gateway/info");
}

export async function fetchGatewaySettings(): Promise<GatewaySettings> {
  return apiJson<GatewaySettings>("/gateway/settings");
}

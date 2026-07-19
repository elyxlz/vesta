import { getConnection } from "@/lib/connection";
import type { GatewayVersionInfo, LogEvent, ReleaseChannel } from "@/lib/types";
import { apiJson } from "./client";
import { openLogStream } from "./log-stream";

const VERSION_FETCH_TIMEOUT_MS = 5000;

// The gateway's cached /version read: version + update availability. Null on any failure,
// so the version gate treats an unreachable gateway as "keep trying" rather than a mismatch.
export async function fetchVersionInfo(): Promise<GatewayVersionInfo | null> {
  try {
    return await apiJson<GatewayVersionInfo>("/version", {
      signal: AbortSignal.timeout(VERSION_FETCH_TIMEOUT_MS),
    });
  } catch {
    return null;
  }
}

let gatewayLogSource: EventSource | null = null;

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

    gatewayLogSource?.close();
    gatewayLogSource = openLogStream(url, "gateway_stopped", onEvent, () => {
      gatewayLogSource = null;
      resolve();
    });
  });
}

export function stopGatewayLogs(): void {
  if (gatewayLogSource) {
    gatewayLogSource.close();
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

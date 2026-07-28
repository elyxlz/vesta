import { mediaUrl } from "@/lib/authed-url";
import type { ReleaseChannel, SseHandle } from "@vesta/core";
import type { LogEvent } from "@/lib/types";
import { apiJson } from "./client";
import { openLogStream } from "./log-stream";

let gatewayLogSource: SseHandle | null = null;

export function streamGatewayLogs(
  follow: boolean,
  onEvent: (event: LogEvent) => void,
): Promise<void> {
  const params = new URLSearchParams();
  if (follow) params.set("follow", "true");
  return new Promise((resolve, reject) => {
    mediaUrl("/gateway/logs", params)
      .then((url) => {
        gatewayLogSource?.cancel();
        gatewayLogSource = openLogStream(
          url,
          "gateway_stopped",
          onEvent,
          () => {
            gatewayLogSource = null;
            resolve();
          },
        );
      })
      .catch(reject);
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

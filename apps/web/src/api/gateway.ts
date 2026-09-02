import * as core from "@vesta/core";
import type { GatewaySettings, SseHandle } from "@vesta/core";
import type { LogEvent } from "@/lib/types";
import { httpClient } from "./client";
import { openLogStream } from "./log-stream";

// Bound to the app's one HttpClient so call sites keep their import path.
// LEGACY(remove-when: the chat-session epic points call sites at @vesta/core directly).

export type {
  GatewayEndpointInfo as GatewayInfo,
  GatewaySettings,
} from "@vesta/core";

let gatewayLogSource: SseHandle | null = null;

export function streamGatewayLogs(
  follow: boolean,
  onEvent: (event: LogEvent) => void,
): Promise<void> {
  return new Promise((resolve) => {
    gatewayLogSource?.cancel();
    gatewayLogSource = openLogStream(
      core.gatewayLogsPath(follow),
      "gateway_stopped",
      onEvent,
      () => {
        gatewayLogSource = null;
        resolve();
      },
    );
  });
}

export function stopGatewayLogs(): void {
  if (gatewayLogSource) {
    gatewayLogSource.cancel();
    gatewayLogSource = null;
  }
}

export const fetchGatewayInfo = () => core.fetchGatewayInfo(httpClient);
export const fetchGatewaySettings = () => core.fetchGatewaySettings(httpClient);
export const updateGatewaySettings = (
  patch: Partial<Pick<GatewaySettings, "auto_update" | "channel">>,
) => core.updateGatewaySettings(httpClient, patch);

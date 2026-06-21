import { getConnection } from "@/lib/connection";
import type { LogEvent } from "@/lib/types";
import { openLogStream } from "./log-stream";

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

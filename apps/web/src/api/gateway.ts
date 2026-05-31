import { getConnection } from "@/lib/connection";
import type { LogEvent } from "@/lib/types";

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

    if (gatewayLogSource) gatewayLogSource.close();
    const es = new EventSource(url);
    gatewayLogSource = es;

    es.onmessage = (e) => {
      const text = e.data;
      if (text.startsWith("error:")) {
        onEvent({ kind: "Error", message: text });
      } else {
        onEvent({ kind: "Line", text });
      }
    };

    es.addEventListener("gateway_stopped", () => {
      onEvent({ kind: "End" });
      es.close();
      gatewayLogSource = null;
      resolve();
    });

    es.onerror = () => {
      onEvent({ kind: "Error", message: "log stream disconnected" });
      es.close();
      gatewayLogSource = null;
      resolve();
    };
  });
}

export function stopGatewayLogs(): void {
  if (gatewayLogSource) {
    gatewayLogSource.close();
    gatewayLogSource = null;
  }
}

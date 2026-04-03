import { getConnection } from "@/lib/connection";
import type { LogEvent } from "@/lib/types";

const logSources = new Map<string, EventSource>();

export function streamLogs(
  name: string,
  onEvent: (event: LogEvent) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const conn = getConnection();
    if (!conn) {
      reject(new Error("not connected"));
      return;
    }

    const url = `${conn.url}/agents/${encodeURIComponent(name)}/logs?token=${encodeURIComponent(conn.accessToken)}`;
    const es = new EventSource(url);
    logSources.set(name, es);

    es.onmessage = (e) => {
      const text = e.data;
      if (text.startsWith("error:")) {
        onEvent({ kind: "Error", message: text });
      } else {
        onEvent({ kind: "Line", text });
      }
    };

    es.addEventListener("agent_stopped", () => {
      onEvent({ kind: "End" });
      es.close();
      logSources.delete(name);
      resolve();
    });

    es.onerror = () => {
      onEvent({ kind: "Error", message: "log stream disconnected" });
      es.close();
      logSources.delete(name);
      resolve();
    };
  });
}

export async function stopLogs(name: string): Promise<void> {
  const es = logSources.get(name);
  if (es) {
    es.close();
    logSources.delete(name);
  }
}

import { getConnection } from "@/lib/connection";
import type { LogEvent } from "@/lib/types";
import { openLogStream } from "./log-stream";

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
    logSources.get(name)?.close();
    logSources.set(
      name,
      openLogStream(url, "agent_stopped", onEvent, () => {
        logSources.delete(name);
        resolve();
      }),
    );
  });
}

export async function stopLogs(name: string): Promise<void> {
  const es = logSources.get(name);
  if (es) {
    es.close();
    logSources.delete(name);
  }
}

import { getConnection } from "@/lib/connection";
import type { LogEvent } from "@/lib/types";
import { openLogStream } from "./log-stream";

const logSources = new Map<string, EventSource>();

export function streamLogs(
  name: string,
  onEvent: (event: LogEvent) => void,
  opts?: { replay?: boolean },
): Promise<void> {
  return new Promise((resolve, reject) => {
    const conn = getConnection();
    if (!conn) {
      reject(new Error("not connected"));
      return;
    }

    // A fresh stream replays the recent tail; a reconnect after a transport drop
    // passes tail=0 so the server follows new lines only and we don't re-append
    // the same block as duplicates.
    const replay = opts?.replay ?? true;
    const tailParam = replay ? "" : "&tail=0";
    const url = `${conn.url}/agents/${encodeURIComponent(name)}/logs?token=${encodeURIComponent(conn.accessToken)}${tailParam}`;
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

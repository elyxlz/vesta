import type { SseHandle } from "@vesta/core";
import { getConnection } from "@/lib/connection";
import { replayTailLines } from "@/lib/log-stream-policy";
import type { LogEvent } from "@/lib/types";
import { openLogStream } from "./log-stream";

const logSources = new Map<string, SseHandle>();

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

    const params = new URLSearchParams({
      token: conn.accessToken,
      tail: String(replayTailLines(opts?.replay ?? true)),
    });
    const url = `${conn.url}/agents/${encodeURIComponent(name)}/logs?${params.toString()}`;
    logSources.get(name)?.cancel();
    logSources.set(
      name,
      openLogStream(url, "agent_stopped", onEvent, () => {
        logSources.delete(name);
        resolve();
      }),
    );
  });
}

export function stopLogs(name: string): Promise<void> {
  const handle = logSources.get(name);
  if (handle) {
    handle.cancel();
    logSources.delete(name);
  }
  return Promise.resolve();
}

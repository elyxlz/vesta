import type { SseHandle } from "@vesta/core";
import { replayTailLines } from "@/lib/log-stream-policy";
import type { LogEvent } from "@/lib/types";
import { openLogStream } from "./log-stream";

const logSources = new Map<string, SseHandle>();

export function streamLogs(
  name: string,
  onEvent: (event: LogEvent) => void,
  opts?: { replay?: boolean },
): Promise<void> {
  const params = new URLSearchParams({
    tail: String(replayTailLines(opts?.replay ?? true)),
  });
  return new Promise((resolve) => {
    logSources.get(name)?.cancel();
    logSources.set(
      name,
      openLogStream(
        `/agents/${encodeURIComponent(name)}/logs?${params.toString()}`,
        "agent_stopped",
        onEvent,
        () => {
          logSources.delete(name);
          resolve();
        },
      ),
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

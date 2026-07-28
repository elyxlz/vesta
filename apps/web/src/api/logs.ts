import type { SseHandle } from "@vesta/core";
import { mediaUrl } from "@/lib/authed-url";
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
  return new Promise((resolve, reject) => {
    mediaUrl(`/agents/${encodeURIComponent(name)}/logs`, params)
      .then((url) => {
        logSources.get(name)?.cancel();
        logSources.set(
          name,
          openLogStream(url, "agent_stopped", onEvent, () => {
            logSources.delete(name);
            resolve();
          }),
        );
      })
      .catch(reject);
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

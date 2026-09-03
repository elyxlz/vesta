import { agentLogsPath, gatewayLogsPath, type SseHandle } from "@vesta/core";
import { replayTailLines } from "@/lib/log-stream-policy";
import type { LogEvent } from "@/lib/types";
import { openLogStream } from "./log-stream";

const logSources = new Map<string, SseHandle>();

export function streamLogs(
  name: string,
  onEvent: (event: LogEvent) => void,
  opts?: { replay?: boolean },
): Promise<void> {
  return new Promise((resolve) => {
    logSources.get(name)?.cancel();
    logSources.set(
      name,
      openLogStream(
        agentLogsPath(name, replayTailLines(opts?.replay ?? true)),
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

let gatewayLogSource: SseHandle | null = null;

export function streamGatewayLogs(
  follow: boolean,
  onEvent: (event: LogEvent) => void,
): Promise<void> {
  return new Promise((resolve) => {
    gatewayLogSource?.cancel();
    gatewayLogSource = openLogStream(
      gatewayLogsPath(follow),
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

import { useEffect, useRef, useState } from "react";
import {
  gatewayLogsPath,
  readSse,
  type SseHandle,
  type StreamEvent,
} from "@vesta/core";
import type { ApiClient } from "@/api/client";
import { LogList } from "@/agent/log-list";
import { addLatestLogLine, type LogLine } from "@/agent/log-list-model";
import {
  LOG_RETRY_DELAY_MS,
  LOG_RETRY_MAX_DELAY_MS,
  subscribeLogs,
} from "@/agent/log-stream-subscription";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { SheetChrome } from "@/components/sheet-chrome";
import { SheetTitle } from "@/components/sheet-title";
import { useSession } from "@/session/SessionProvider";

// The gateway's own log, read over the api client like the agent log so the stream presents
// `Authorization: Bearer` and refreshes an expiring token first.
function openGatewayLogStream(
  api: ApiClient,
  onEvent: (event: StreamEvent) => void,
): SseHandle {
  return readSse(
    {
      fetch: api.request,
      url: gatewayLogsPath(true),
      stoppedEvent: "gateway_stopped",
    },
    onEvent,
  );
}

function GatewayLogs() {
  const { api } = useSession();
  const [logs, setLogs] = useState<LogLine[]>([]);
  const logsRef = useRef(logs);
  const nextLogId = useRef(0);
  const [logError, setLogError] = useState("");

  useEffect(
    () =>
      subscribeLogs({
        // The gateway replays its tail on every open, so a reconnect starts the list over
        // instead of appending the replay a second time.
        open: (reconnect, onEvent) => {
          if (reconnect) {
            logsRef.current = [];
            setLogs([]);
          }
          return openGatewayLogStream(api, onEvent);
        },
        onLine: (text) => {
          setLogError("");
          const id = nextLogId.current;
          nextLogId.current += 1;
          const next = addLatestLogLine(logsRef.current, { id, text });
          logsRef.current = next;
          setLogs(next);
        },
        onError: setLogError,
        retryDelayMs: LOG_RETRY_DELAY_MS,
        maxRetryDelayMs: LOG_RETRY_MAX_DELAY_MS,
      }),
    [api],
  );

  return <LogList logs={logs} logError={logError} presentation="standalone" />;
}

export default function GatewayLogsScreen() {
  return (
    <>
      <SheetTitle>Gateway logs</SheetTitle>
      <NativeSheetCloseButton accessibilityLabel="Close gateway logs" />
      <SheetChrome title="Gateway logs" closeLabel="Close gateway logs" />
      <GatewayLogs />
    </>
  );
}

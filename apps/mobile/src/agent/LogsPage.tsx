import { useEffect, useRef, useState } from "react";
import type { ApiClient } from "@/api/client";
import { useAgent } from "@/agent/AgentProvider";
import { openAgentLogStream } from "@/agent/agent-log-stream";
import { LogList, type LogPresentation } from "@/agent/log-list";
import { addLatestLogLine, type LogLine } from "@/agent/log-list-model";
import {
  LOG_RETRY_DELAY_MS,
  LOG_RETRY_MAX_DELAY_MS,
  subscribeLogs,
} from "@/agent/log-stream-subscription";
import { agentHoldKey } from "@vesta/core";
import { agentHolds } from "@/holds/agent-holds";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";

interface LogsPageProps {
  presentation?: LogPresentation;
}

export default function LogsPage({ presentation = "pager" }: LogsPageProps) {
  const { api, connection } = useSession();
  const { reachable } = useRoster();
  const { name } = useAgent();
  const holdKey = agentHoldKey(name, connectionKeyOf(connection) ?? "");
  // Stream whenever the gateway is reachable: vestad serves a stopped agent's log-file tail and
  // ends the stream cleanly, so a dead agent's last lines stay diagnosable. The held buffer keeps
  // the last session's lines on screen while the gateway itself is unreachable.
  return reachable ? (
    <LiveLogs
      key={holdKey}
      api={api}
      name={name}
      holdKey={holdKey}
      presentation={presentation}
    />
  ) : (
    <LogList
      logs={agentHolds.logs.read(holdKey) ?? []}
      logError=""
      presentation={presentation}
    />
  );
}

function LiveLogs({
  api,
  name,
  holdKey,
  presentation,
}: {
  api: ApiClient;
  name: string;
  holdKey: string;
  presentation: LogPresentation;
}) {
  // Each mount starts empty and replays the tail, so lines logged while unmounted are refetched
  // rather than silently missing; the hold only backs the not-reachable fallback view.
  const [logs, setLogs] = useState<LogLine[]>([]);
  const logsRef = useRef(logs);
  const nextLogId = useRef(0);
  const [logError, setLogError] = useState("");

  useEffect(
    () =>
      subscribeLogs({
        open: (reconnect, onEvent) =>
          openAgentLogStream(api, name, reconnect, onEvent),
        onLine: (text) => {
          setLogError("");
          const id = nextLogId.current;
          nextLogId.current += 1;
          const next = addLatestLogLine(logsRef.current, { id, text });
          logsRef.current = next;
          setLogs(next);
          agentHolds.logs.persist(holdKey, next);
        },
        onError: setLogError,
        retryDelayMs: LOG_RETRY_DELAY_MS,
        maxRetryDelayMs: LOG_RETRY_MAX_DELAY_MS,
      }),
    [api, name, holdKey],
  );

  return (
    <LogList logs={logs} logError={logError} presentation={presentation} />
  );
}

import { useEffect, useRef, useState } from "react";
import { FlatList, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { ApiClient } from "@/api/client";
import { useAgent } from "@/agent/AgentProvider";
import { openAgentLogStream } from "@/agent/agent-log-stream";
import { addLatestLogLine, type LogLine } from "@/agent/log-list-model";
import { subscribeLogs } from "@/agent/log-stream-subscription";
import { AnsiText } from "@/components/ui/AnsiText";
import { Text } from "@/components/ui/Typography";
import { useAgentHolds, type AgentHolds } from "@/holds/AgentHoldsProvider";
import { agentHoldKey } from "@/holds/keyed-hold";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";
import { navHeaderHeight } from "@/theme/layout";

const LOG_RETRY_DELAY_MS = 1_000;
const LOG_RETRY_MAX_DELAY_MS = 30_000;
// Visual-top chrome the pager overlays on the list (agent header + page dots).
const PAGER_HEADER_HEIGHT = 104;
// Lines prepend at index 0, the visual bottom of the inverted list. Holding the
// first visible line in place keeps arrivals from shifting the view mid-read;
// within the threshold of the newest line the list follows the tail instead.
const FOLLOW_TAIL = { minIndexForVisible: 0, autoscrollToTopThreshold: 32 };

interface LogsPageProps {
  presentation?: "pager" | "standalone";
}

export default function LogsPage({ presentation = "pager" }: LogsPageProps) {
  const { api, connection } = useSession();
  const { reachable } = useRoster();
  const { name } = useAgent();
  const holds = useAgentHolds();
  const holdKey = agentHoldKey(name, connectionKeyOf(connection) ?? "");
  // Stream whenever the gateway is reachable: vestad serves a stopped agent's log-file tail and
  // ends the stream cleanly, so a dead agent's last lines stay diagnosable. The held buffer keeps
  // the last session's lines on screen while the gateway itself is unreachable.
  return reachable ? (
    <LiveLogs
      key={holdKey}
      api={api}
      name={name}
      holds={holds}
      holdKey={holdKey}
      presentation={presentation}
    />
  ) : (
    <LogList
      logs={holds.logs.read(holdKey) ?? []}
      logError=""
      presentation={presentation}
    />
  );
}

function LiveLogs({
  api,
  name,
  holds,
  holdKey,
  presentation,
}: {
  api: ApiClient;
  name: string;
  holds: AgentHolds;
  holdKey: string;
  presentation: NonNullable<LogsPageProps["presentation"]>;
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
          holds.logs.persist(holdKey, next);
        },
        onError: setLogError,
        retryDelayMs: LOG_RETRY_DELAY_MS,
        maxRetryDelayMs: LOG_RETRY_MAX_DELAY_MS,
      }),
    [api, name, holds, holdKey],
  );

  return (
    <LogList
      logs={logs}
      logError={logError}
      presentation={presentation}
    />
  );
}

function LogList({
  logs,
  logError,
  presentation,
}: {
  logs: LogLine[];
  logError: string;
  presentation: NonNullable<LogsPageProps["presentation"]>;
}) {
  const { colors } = usePreferences();
  const insets = useSafeAreaInsets();
  const topChrome =
    presentation === "standalone" ? navHeaderHeight : PAGER_HEADER_HEIGHT;

  return (
    <View style={styles.screen}>
      <FlatList
        style={styles.list}
        data={logs}
        inverted
        maintainVisibleContentPosition={FOLLOW_TAIL}
        keyExtractor={(line) => String(line.id)}
        renderItem={({ item }) => (
          <AnsiText value={item.text} selectable style={styles.logLine} />
        )}
        automaticallyAdjustContentInsets={false}
        contentInsetAdjustmentBehavior="never"
        contentContainerStyle={[
          styles.listContent,
          {
            paddingTop: insets.bottom,
            paddingBottom: insets.top + topChrome,
          },
        ]}
        ListHeaderComponent={
          logError ? (
            <Text style={[styles.logError, { color: colors.warning }]}>
              {logError}
            </Text>
          ) : null
        }
        ListEmptyComponent={
          <Text style={[styles.empty, { color: colors.secondaryText }]}>
            Waiting for logs…
          </Text>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  list: { flex: 1 },
  listContent: { paddingHorizontal: 12 },
  logLine: { fontSize: 13, lineHeight: 18 },
  logError: { paddingBottom: 8, paddingHorizontal: 2, fontSize: 12 },
  empty: { textAlign: "center", padding: 40, fontSize: 14 },
});

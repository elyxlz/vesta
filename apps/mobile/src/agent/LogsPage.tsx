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
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";
import { navHeaderHeight } from "@/theme/layout";

const LOG_RETRY_DELAY_MS = 1_000;
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
  const { api } = useSession();
  const { reachable } = useRoster();
  const { name } = useAgent();

  return reachable ? (
    <LiveLogs
      key={name}
      api={api}
      name={name}
      presentation={presentation}
    />
  ) : (
    <LogList logs={[]} logError="" presentation={presentation} />
  );
}

function LiveLogs({
  api,
  name,
  presentation,
}: {
  api: ApiClient;
  name: string;
  presentation: NonNullable<LogsPageProps["presentation"]>;
}) {
  const [logs, setLogs] = useState<LogLine[]>([]);
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
          setLogs((current) => addLatestLogLine(current, { id, text }));
        },
        onError: setLogError,
        retryDelayMs: LOG_RETRY_DELAY_MS,
      }),
    [api, name],
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

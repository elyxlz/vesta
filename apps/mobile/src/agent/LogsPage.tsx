import { useEffect, useRef, useState } from "react";
import { FlatList, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { ApiClient } from "@/api/client";
import { streamLogs, type LogEvent } from "@/api/log-stream";
import { useAgent } from "@/agent/AgentProvider";
import { addLatestLogLine, type LogLine } from "@/agent/log-list-model";
import { AnsiText } from "@/components/ui/AnsiText";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";

const LOG_RETRY_DELAY_MS = 1_000;

export default function LogsPage() {
  const { api } = useSession();
  const { reachable } = useRoster();
  const { name } = useAgent();

  return reachable ? (
    <LiveLogs key={name} api={api} name={name} />
  ) : (
    <LogList logs={[]} logError="" />
  );
}

function LiveLogs({ api, name }: { api: ApiClient; name: string }) {
  const [logs, setLogs] = useState<LogLine[]>([]);
  const nextLogId = useRef(0);
  const [logError, setLogError] = useState("");

  useEffect(() => {
    const abort = new AbortController();
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let receivedLine = false;

    const openStream = async (): Promise<void> => {
      let agentStopped = false;
      const tail = receivedLine ? "?tail=0" : "";
      await streamLogs(
        api,
        `/agents/${encodeURIComponent(name)}/logs${tail}`,
        "agent_stopped",
        abort.signal,
        (event: LogEvent) => {
          if (event.kind === "Line") {
            receivedLine = true;
            setLogError("");
            const id = nextLogId.current;
            nextLogId.current += 1;
            setLogs((current) =>
              addLatestLogLine(current, { id, text: event.text }),
            );
          } else if (event.kind === "Error") {
            setLogError(event.message);
          } else {
            agentStopped = true;
          }
        },
      );

      if (abort.signal.aborted || agentStopped) return;
      retryTimer = setTimeout(() => void openStream(), LOG_RETRY_DELAY_MS);
    };

    void openStream();
    return () => {
      abort.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [api, name]);

  return <LogList logs={logs} logError={logError} />;
}

function LogList({ logs, logError }: { logs: LogLine[]; logError: string }) {
  const { colors } = usePreferences();
  const insets = useSafeAreaInsets();

  return (
    <View style={styles.screen}>
      <FlatList
        style={styles.list}
        data={logs}
        inverted
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
            paddingBottom: insets.top + 104,
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

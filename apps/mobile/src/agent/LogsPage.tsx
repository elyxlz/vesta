import { useEffect, useRef, useState } from "react";
import { FlatList, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { streamLogs, type LogEvent } from "@/api/log-stream";
import { useAgent } from "@/agent/AgentProvider";
import { addLatestLogLine, type LogLine } from "@/agent/log-list-model";
import { AnsiText } from "@/components/ui/AnsiText";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

export default function LogsPage() {
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const insets = useSafeAreaInsets();
  const [logs, setLogs] = useState<LogLine[]>([]);
  const nextLogId = useRef(0);
  const [logError, setLogError] = useState("");

  useEffect(() => {
    const abort = new AbortController();
    void streamLogs(
      api,
      `/agents/${encodeURIComponent(name)}/logs`,
      "agent_stopped",
      abort.signal,
      (event: LogEvent) => {
        if (event.kind === "Line") {
          const id = nextLogId.current;
          nextLogId.current += 1;
          setLogs((current) =>
            addLatestLogLine(current, { id, text: event.text }),
          );
        } else if (event.kind === "Error") {
          setLogError(event.message);
        }
      },
    );
    return () => abort.abort();
  }, [api, name]);

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

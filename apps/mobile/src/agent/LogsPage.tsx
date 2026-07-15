import { useEffect, useRef, useState } from "react";
import { FlatList, StyleSheet, View } from "react-native";
import { streamLogs, type LogEvent } from "@/api/log-stream";
import { useAgent } from "@/agent/AgentProvider";
import { AnsiText } from "@/components/ui/AnsiText";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

interface LogLine {
  id: number;
  text: string;
}

export default function LogsPage() {
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
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
            [...current, { id, text: event.text }].slice(-5000),
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
        keyExtractor={(line) => String(line.id)}
        renderItem={({ item }) => (
          <AnsiText value={item.text} selectable style={styles.logLine} />
        )}
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={styles.listContent}
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
  listContent: { paddingHorizontal: 12, paddingBottom: 88 },
  logLine: { fontSize: 11, lineHeight: 16 },
  logError: { paddingBottom: 8, paddingHorizontal: 2, fontSize: 12 },
  empty: { textAlign: "center", padding: 40, fontSize: 14 },
});

import { readSse, type SseHandle } from "@vesta/core";
import { useEffect, useRef, useState } from "react";
import { FlatList, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { ApiClient } from "@/api/client";
import { useAgent } from "@/agent/AgentProvider";
import { addLatestLogLine, type LogLine } from "@/agent/log-list-model";
import { useBottomAnchoredFeed } from "@/agent/use-bottom-anchored-feed";
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

  useEffect(() => {
    let cancelled = false;
    let handle: SseHandle | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let receivedLine = false;

    const openStream = (): void => {
      const query = receivedLine
        ? new URLSearchParams({ tail: "0" })
        : undefined;
      handle = readSse(
        {
          fetch: (url, init) => fetch(url, init),
          url: api.mediaUrl(`/agents/${encodeURIComponent(name)}/logs`, query),
          stoppedEvent: "agent_stopped",
        },
        (event) => {
          if (cancelled) return;
          if (event.kind === "line") {
            receivedLine = true;
            setLogError("");
            const id = nextLogId.current;
            nextLogId.current += 1;
            setLogs((current) =>
              addLatestLogLine(current, { id, text: event.text }),
            );
          } else if (event.kind === "error") {
            setLogError(event.message);
            retryTimer = setTimeout(openStream, LOG_RETRY_DELAY_MS);
          }
        },
      );
    };

    openStream();
    return () => {
      cancelled = true;
      handle?.cancel();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [api, name]);

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
  const standalone = presentation === "standalone";
  const displayLogs = useMemo(
    () => (standalone ? [...logs].reverse() : logs),
    [logs, standalone],
  );
  const bottomAnchor = useBottomAnchoredFeed<LogLine>(displayLogs.length);

  return (
    <View style={styles.screen}>
      <FlatList
        ref={standalone ? bottomAnchor.listRef : undefined}
        style={[
          styles.list,
          standalone && !bottomAnchor.contentVisible
            ? styles.positioningList
            : null,
        ]}
        data={displayLogs}
        inverted={!standalone}
        keyExtractor={(line) => String(line.id)}
        renderItem={({ item }) => (
          <AnsiText value={item.text} selectable style={styles.logLine} />
        )}
        automaticallyAdjustContentInsets={standalone}
        contentInsetAdjustmentBehavior={standalone ? "automatic" : "never"}
        contentContainerStyle={
          standalone
            ? styles.listContent
            : [
                styles.listContent,
                {
                  paddingTop: insets.bottom,
                  paddingBottom: insets.top + 104,
                },
              ]
        }
        onContentSizeChange={
          standalone ? bottomAnchor.onContentSizeChange : undefined
        }
        onScroll={standalone ? bottomAnchor.onScroll : undefined}
        scrollEventThrottle={standalone ? 16 : undefined}
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
  positioningList: { opacity: 0 },
  listContent: { paddingHorizontal: 12 },
  logLine: { fontSize: 13, lineHeight: 18 },
  logError: { paddingBottom: 8, paddingHorizontal: 2, fontSize: 12 },
  empty: { textAlign: "center", padding: 40, fontSize: 14 },
});

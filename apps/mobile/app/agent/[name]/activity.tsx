import { useEffect, useRef, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  View,
} from "react-native";
import { useQuery } from "@tanstack/react-query";
import { Stack } from "expo-router";
import { getNotificationHistory } from "@/api/endpoints";
import { streamLogs, type LogEvent } from "@/api/log-stream";
import type { NotificationEvent } from "@/api/types";
import { AgentProvider, useAgent } from "@/agent/AgentProvider";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

type ActivityTab = "notifications" | "logs";

interface LogLine {
  id: number;
  text: string;
}

function Segment({
  value,
  selected,
  onPress,
}: {
  value: string;
  selected: boolean;
  onPress: () => void;
}) {
  const { colors } = usePreferences();
  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={[
        styles.segment,
        { backgroundColor: selected ? colors.card : "transparent" },
      ]}
    >
      <Text style={[styles.segmentLabel, { color: selected ? colors.text : colors.secondaryText }]}>{value}</Text>
    </Pressable>
  );
}

function NotificationRow({ event, pending }: { event: NotificationEvent; pending: boolean }) {
  const { colors } = usePreferences();
  const accent = event.decided === "interrupt" ? colors.warning : event.decided === "trash" ? colors.tertiaryText : colors.accent;
  return (
    <View style={[styles.notification, { backgroundColor: colors.card, borderColor: colors.border }]}>
      <View style={styles.notificationTop}>
        <View style={[styles.sourceDot, { backgroundColor: accent }]} />
        <Text style={[styles.source, { color: colors.secondaryText }]}>{event.source}</Text>
        {pending ? <Text style={[styles.pending, { color: colors.warning }]}>pending</Text> : null}
        {event.ts ? <Text style={[styles.time, { color: colors.tertiaryText }]}>{new Date(event.ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</Text> : null}
      </View>
      {event.sender ? <Text style={[styles.sender, { color: colors.text }]}>{event.sender}</Text> : null}
      <Text style={[styles.summary, { color: colors.secondaryText }]}>{event.summary}</Text>
    </View>
  );
}

function stripAnsi(value: string): string {
  return value.replace(/\u001B(?:[@-_]|\[[0-?]*[ -/]*[@-~])/g, "");
}

function ActivityContent() {
  const { api } = useSession();
  const { name, socket } = useAgent();
  const { colors } = usePreferences();
  const [tab, setTab] = useState<ActivityTab>("notifications");
  const [logs, setLogs] = useState<LogLine[]>([]);
  const nextLogId = useRef(0);
  const [logError, setLogError] = useState("");
  const notifications = useQuery({
    queryKey: ["notifications", name],
    queryFn: () => getNotificationHistory(api, name),
  });

  useEffect(() => {
    if (tab !== "logs") return;
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
          setLogs((current) => [
            ...current,
            { id, text: stripAnsi(event.text) },
          ].slice(-5000));
        } else if (event.kind === "Error") {
          setLogError(event.message);
        }
      },
    );
    return () => abort.abort();
  }, [api, name, tab]);

  const notificationItems = notifications.data?.notifications ?? [];
  const tabs = (
    <View
      style={[
        styles.tabsHeader,
        { backgroundColor: colors.background },
      ]}
    >
      <View style={[styles.segments, { backgroundColor: colors.input }]}>
        <Segment
          value="Notifications"
          selected={tab === "notifications"}
          onPress={() => setTab("notifications")}
        />
        <Segment
          value="Logs"
          selected={tab === "logs"}
          onPress={() => {
            setLogError("");
            setTab("logs");
          }}
        />
      </View>
      {tab === "logs" && logError ? (
        <Text style={[styles.logError, { color: colors.warning }]}>
          {logError}
        </Text>
      ) : null}
    </View>
  );
  return (
    <View style={styles.screen}>
      <Stack.Screen options={{ title: "Activity" }} />
      {tab === "notifications" ? (
        <FlatList
          style={styles.list}
          data={notificationItems}
          keyExtractor={(event, index) =>
            `${event.notif_id ?? `${event.ts}-${event.source}`}-${index}`
          }
          renderItem={({ item }) => (
            <NotificationRow
              event={item}
              pending={Boolean(item.notif_id && socket.pendingNotifications.includes(item.notif_id))}
            />
          )}
          contentInsetAdjustmentBehavior="automatic"
          contentContainerStyle={styles.listContent}
          ListHeaderComponent={tabs}
          stickyHeaderIndices={[0]}
          refreshControl={<RefreshControl refreshing={notifications.isFetching} onRefresh={() => void notifications.refetch()} tintColor={colors.accent} />}
          ListEmptyComponent={<Text style={[styles.empty, { color: colors.secondaryText }]}>No notifications yet.</Text>}
        />
      ) : (
        <FlatList
          style={styles.list}
          data={logs}
          keyExtractor={(line) => String(line.id)}
          renderItem={({ item }) => <Text family="mono" selectable style={[styles.logLine, { color: colors.secondaryText }]}>{item.text}</Text>}
          contentInsetAdjustmentBehavior="automatic"
          contentContainerStyle={styles.listContent}
          ListHeaderComponent={tabs}
          stickyHeaderIndices={[0]}
          ListEmptyComponent={<Text style={[styles.empty, { color: colors.secondaryText }]}>Waiting for logs…</Text>}
        />
      )}
    </View>
  );
}

export default function ActivityScreen() {
  return (
    <AgentProvider>
      <ActivityContent />
    </AgentProvider>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  tabsHeader: { paddingTop: 12, paddingBottom: 8 },
  segments: { flexDirection: "row", padding: 3, borderRadius: 11 },
  segment: { flex: 1, minHeight: 34, justifyContent: "center", alignItems: "center", borderRadius: 9 },
  segmentLabel: { fontSize: 13, fontWeight: "700" },
  list: { flex: 1 },
  listContent: { paddingHorizontal: 12, paddingBottom: 88 },
  notification: { borderRadius: 17, borderWidth: StyleSheet.hairlineWidth, padding: 13, gap: 5, marginBottom: 9 },
  notificationTop: { flexDirection: "row", alignItems: "center", gap: 6 },
  sourceDot: { width: 7, height: 7, borderRadius: 4 },
  source: { fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  pending: { fontSize: 11, fontWeight: "700" },
  time: { marginLeft: "auto", fontSize: 10 },
  sender: { fontSize: 15, fontWeight: "700" },
  summary: { fontSize: 14, lineHeight: 19 },
  empty: { textAlign: "center", padding: 40, fontSize: 14 },
  logLine: { fontSize: 11, lineHeight: 16 },
  logError: { paddingTop: 8, paddingHorizontal: 2, fontSize: 12 },
});

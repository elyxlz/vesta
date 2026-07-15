import { FlatList, RefreshControl, StyleSheet, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { getNotificationHistory } from "@/api/endpoints";
import type { NotificationEvent } from "@/api/types";
import { useAgent } from "@/agent/AgentProvider";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

function NotificationRow({
  event,
  pending,
}: {
  event: NotificationEvent;
  pending: boolean;
}) {
  const { colors } = usePreferences();
  const accent =
    event.decided === "interrupt"
      ? colors.warning
      : event.decided === "trash"
        ? colors.tertiaryText
        : colors.accent;

  return (
    <View
      style={[
        styles.notification,
        { backgroundColor: colors.card, borderColor: colors.border },
      ]}
    >
      <View style={styles.notificationTop}>
        <View style={[styles.sourceDot, { backgroundColor: accent }]} />
        <Text style={[styles.source, { color: colors.secondaryText }]}>
          {event.source}
        </Text>
        {pending ? (
          <Text style={[styles.pending, { color: colors.warning }]}>
            pending
          </Text>
        ) : null}
        {event.ts ? (
          <Text style={[styles.time, { color: colors.tertiaryText }]}>
            {new Date(event.ts).toLocaleString([], {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </Text>
        ) : null}
      </View>
      {event.sender ? (
        <Text style={[styles.sender, { color: colors.text }]}>
          {event.sender}
        </Text>
      ) : null}
      <Text style={[styles.summary, { color: colors.secondaryText }]}>
        {event.summary}
      </Text>
    </View>
  );
}

export default function NotificationsPage() {
  const { api } = useSession();
  const { name, socket } = useAgent();
  const { colors } = usePreferences();
  const notifications = useQuery({
    queryKey: ["notifications", name],
    queryFn: () => getNotificationHistory(api, name),
  });
  const items = notifications.data?.notifications ?? [];

  return (
    <View style={styles.screen}>
      <FlatList
        style={styles.list}
        data={items}
        keyExtractor={(event, index) =>
          `${event.notif_id ?? `${event.ts}-${event.source}`}-${index}`
        }
        renderItem={({ item }) => (
          <NotificationRow
            event={item}
            pending={Boolean(
              item.notif_id &&
              socket.pendingNotifications.includes(item.notif_id),
            )}
          />
        )}
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={styles.listContent}
        refreshControl={
          <RefreshControl
            refreshing={notifications.isFetching}
            onRefresh={() => void notifications.refetch()}
            tintColor={colors.accent}
          />
        }
        ListEmptyComponent={
          <Text style={[styles.empty, { color: colors.secondaryText }]}>
            No notifications yet.
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
  notification: {
    borderRadius: 17,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 13,
    gap: 5,
    marginBottom: 9,
  },
  notificationTop: { flexDirection: "row", alignItems: "center", gap: 6 },
  sourceDot: { width: 7, height: 7, borderRadius: 4 },
  source: { fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  pending: { fontSize: 11, fontWeight: "700" },
  time: { marginLeft: "auto", fontSize: 10 },
  sender: { fontSize: 15, fontWeight: "700" },
  summary: { fontSize: 14, lineHeight: 19 },
  empty: { textAlign: "center", padding: 40, fontSize: 14 },
});

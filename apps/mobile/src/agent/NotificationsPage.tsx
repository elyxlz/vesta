import { useEffect, useMemo, useRef } from "react";
import { FlatList, StyleSheet, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { getNotificationHistory } from "@/api/endpoints";
import type { NotificationEvent } from "@/api/types";
import { useAgent } from "@/agent/AgentProvider";
import {
  getPendingNotificationIds,
  mergeLiveNotifications,
} from "@/agent/notification-list-model";
import { parseNotificationContent } from "@/agent/notification-content";
import { useBottomAnchoredFeed } from "@/agent/use-bottom-anchored-feed";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { radii } from "@/theme/layout";

function NotificationRow({
  event,
  pending,
}: {
  event: NotificationEvent;
  pending: boolean;
}) {
  const { colors } = usePreferences();
  const decisionColor =
    event.decided === "interrupt"
      ? colors.warning
      : event.decided === "trash"
        ? colors.tertiaryText
        : colors.accent;
  const stateColor = pending ? colors.accent : colors.tertiaryText;
  const decision =
    event.decided === "interrupt"
      ? "interrupted"
      : event.decided === "snooze"
        ? "snoozed"
        : event.decided === "trash"
          ? "trashed"
          : null;
  const content = parseNotificationContent(event);

  return (
    <View
      style={[
        styles.notification,
        {
          backgroundColor: colors.card,
          borderColor: pending ? colors.accent : colors.border,
        },
      ]}
    >
      <View style={styles.notificationTop}>
        <View style={[styles.sourceDot, { backgroundColor: stateColor }]} />
        <Text style={[styles.source, { color: colors.secondaryText }]}>
          {event.source}
        </Text>
        {pending ? (
          <Text style={[styles.pending, { color: colors.accent }]}>
            pending
          </Text>
        ) : null}
        {decision || event.ts ? (
          <View style={styles.notificationMeta}>
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
            {decision ? (
              <Text
                style={[
                  styles.decision,
                  { color: decisionColor, backgroundColor: colors.input },
                ]}
              >
                {decision}
              </Text>
            ) : null}
          </View>
        ) : null}
      </View>
      {event.sender ? (
        <Text style={[styles.sender, { color: colors.text }]}>
          {event.sender}
        </Text>
      ) : null}
      <Text style={[styles.summary, { color: colors.secondaryText }]}>
        {content.headline}
      </Text>
      {content.body ? (
        <Text style={[styles.body, { color: colors.secondaryText }]}>
          {content.body}
        </Text>
      ) : null}
      {content.context ? (
        <Text style={[styles.context, { color: colors.tertiaryText }]}>
          {content.context}
        </Text>
      ) : null}
    </View>
  );
}

interface NotificationsPageProps {
  presentation?: "pager" | "standalone";
}

export default function NotificationsPage({
  presentation = "pager",
}: NotificationsPageProps) {
  const { api } = useSession();
  const { name, socket } = useAgent();
  const { colors } = usePreferences();
  const insets = useSafeAreaInsets();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["notifications", name],
    queryFn: () => getNotificationHistory(api, name),
  });
  const lastSnapshotRevision = useRef(0);
  const items = useMemo(
    () =>
      mergeLiveNotifications(
        data?.notifications ?? [],
        socket.events,
      ),
    [data?.notifications, socket.events],
  );
  const standalone = presentation === "standalone";
  const displayItems = useMemo(
    () => (standalone ? [...items].reverse() : items),
    [items, standalone],
  );
  const bottomAnchor = useBottomAnchoredFeed<NotificationEvent>(
    displayItems.length,
  );
  const pendingIds = useMemo(
    () =>
      getPendingNotificationIds(socket.pendingNotifications, socket.events),
    [socket.events, socket.pendingNotifications],
  );

  useEffect(() => {
    if (
      socket.snapshotRevision === 0 ||
      socket.snapshotRevision === lastSnapshotRevision.current
    ) {
      return;
    }
    lastSnapshotRevision.current = socket.snapshotRevision;
    void refetch();
  }, [refetch, socket.snapshotRevision]);

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
        data={displayItems}
        inverted={!standalone}
        keyExtractor={(event, index) =>
          `${event.notif_id ?? `${event.ts}-${event.source}`}-${index}`
        }
        renderItem={({ item }) => (
          <NotificationRow
            event={item}
            pending={Boolean(item.notif_id && pendingIds.has(item.notif_id))}
          />
        )}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
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
        ListEmptyComponent={
          isLoading ? null : (
            <Text style={[styles.empty, { color: colors.secondaryText }]}>
              No notifications yet.
            </Text>
          )
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
  notification: {
    borderRadius: 17,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 13,
    gap: 5,
  },
  separator: { height: 9 },
  notificationTop: { flexDirection: "row", alignItems: "center", gap: 6 },
  notificationMeta: {
    marginLeft: "auto",
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  sourceDot: { width: 7, height: 7, borderRadius: 4 },
  source: { fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  decision: {
    width: 68,
    borderRadius: radii.pill,
    paddingHorizontal: 7,
    paddingVertical: 3,
    fontSize: 10,
    fontWeight: "600",
    textAlign: "center",
  },
  pending: { fontSize: 11, fontWeight: "700" },
  time: { fontSize: 10 },
  sender: { fontSize: 15, fontWeight: "700" },
  summary: { fontSize: 14, lineHeight: 19 },
  body: { fontSize: 13, lineHeight: 18 },
  context: { fontSize: 11, lineHeight: 15 },
  empty: { textAlign: "center", padding: 40, fontSize: 14 },
});

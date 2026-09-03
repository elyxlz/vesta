import { memo, useCallback, useEffect, useMemo, useRef } from "react";
import { FlatList, StyleSheet, View, type ListRenderItem } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { getNotificationHistory } from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import {
  getPendingNotificationIds,
  mergeLiveNotifications,
} from "@/agent/notification-list-model";
import {
  notificationRowKey,
  parseNotificationContent,
  type NotificationView,
} from "@vesta/core";
import { useBottomAnchoredFeed } from "@/agent/use-bottom-anchored-feed";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { navHeaderHeight, radii } from "@/theme/layout";

// Memoized: row identities are stable across merges, so unrelated chat events re-render no rows,
// and the parsed content plus formatted timestamp are computed once per event.
const NotificationRow = memo(function NotificationRow({
  event,
  pending,
}: {
  event: NotificationView;
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
  const content = useMemo(() => parseNotificationContent(event), [event]);
  const timeLabel = useMemo(
    () =>
      event.ts
        ? new Date(event.ts).toLocaleString([], {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })
        : null,
    [event.ts],
  );

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
        {decision || timeLabel ? (
          <View style={styles.notificationMeta}>
            {timeLabel ? (
              <Text style={[styles.time, { color: colors.tertiaryText }]}>
                {timeLabel}
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
});

// Module-scoped so the separator keeps one component identity across page renders;
// an inline arrow would remount every separator on each render.
function NotificationSeparator() {
  return <View style={styles.separator} />;
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
  const lastReseedRevision = useRef(0);
  const items = useMemo(
    () => mergeLiveNotifications(data?.notifications ?? [], socket.events),
    [data?.notifications, socket.events],
  );
  const standalone = presentation === "standalone";
  const displayItems = useMemo(
    () => (standalone ? [...items].reverse() : items),
    [items, standalone],
  );
  const bottomAnchor = useBottomAnchoredFeed<NotificationView>(
    displayItems.length,
  );
  const pendingIds = useMemo(
    () => getPendingNotificationIds(socket.pendingNotifications, socket.events),
    [socket.events, socket.pendingNotifications],
  );

  useEffect(() => {
    if (
      socket.reseedRevision === 0 ||
      socket.reseedRevision === lastReseedRevision.current
    ) {
      return;
    }
    lastReseedRevision.current = socket.reseedRevision;
    void refetch();
  }, [refetch, socket.reseedRevision]);

  const renderNotification = useCallback<ListRenderItem<NotificationView>>(
    ({ item }) => (
      <NotificationRow
        event={item}
        pending={Boolean(item.notif_id && pendingIds.has(item.notif_id))}
      />
    ),
    [pendingIds],
  );

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
        keyExtractor={notificationRowKey}
        renderItem={renderNotification}
        ItemSeparatorComponent={NotificationSeparator}
        automaticallyAdjustContentInsets={false}
        contentInsetAdjustmentBehavior="never"
        contentContainerStyle={
          standalone
            ? [
                styles.listContent,
                {
                  paddingTop: insets.top + navHeaderHeight,
                  paddingBottom: insets.bottom,
                },
                displayItems.length > 0 ? styles.bottomAligned : null,
              ]
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
        // The sheet lays out every loaded row before its tail scroll, so the end it lands on is
        // the real one rather than the first batch's.
        initialNumToRender={standalone ? displayItems.length : undefined}
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
  bottomAligned: { flexGrow: 1, justifyContent: "flex-end" },
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
    borderCurve: "continuous",
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

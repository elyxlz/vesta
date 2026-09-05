import { Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { roomKind, roomLabel, type Room } from "@vesta/core";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { radii } from "@/theme/layout";
import { relativeTime } from "./relative-time";

// Every conversation on the node, busiest first, under the carousel. A direct room is that agent's
// own page, so its row goes there; every other room has its own screen.
function ChatRow({ room }: { room: Room }) {
  const router = useRouter();
  const { colors } = usePreferences();
  const kind = roomKind(room);
  const label = roomLabel(room);
  const first = room.agents[0];
  // Only a group is titled by something other than its members, so only a group names them
  // underneath: a direct or peer row would just repeat its own title.
  const subtitle = kind === "group" ? room.agents.join(", ") : null;
  const open = () => {
    if (kind === "direct" && first !== undefined) {
      router.push({ pathname: "/agent/[name]", params: { name: first } });
      return;
    }
    router.push({ pathname: "/chat/[roomId]", params: { roomId: room.id } });
  };

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Open ${label} chat`}
      onPress={open}
      style={({ pressed }) => [
        styles.row,
        { backgroundColor: colors.card, opacity: pressed ? 0.6 : 1 },
      ]}
    >
      <View style={[styles.rowIcon, { backgroundColor: colors.input }]}>
        <Ionicons
          name={kind === "direct" ? "chatbubble-outline" : "people-outline"}
          size={17}
          color={colors.secondaryText}
        />
      </View>
      <View style={styles.rowText}>
        <Text
          numberOfLines={1}
          style={[styles.rowLabel, { color: colors.text }]}
        >
          {label}
        </Text>
        {subtitle !== null ? (
          <Text
            numberOfLines={1}
            style={[styles.rowDetail, { color: colors.tertiaryText }]}
          >
            {subtitle}
          </Text>
        ) : null}
      </View>
      {room.lastMessageAt !== null ? (
        <Text style={[styles.rowTime, { color: colors.tertiaryText }]}>
          {relativeTime(room.lastMessageAt)}
        </Text>
      ) : null}
    </Pressable>
  );
}

export function ChatsList() {
  const router = useRouter();
  const { rooms } = useRoster();
  const { colors } = usePreferences();

  return (
    <View style={styles.section}>
      <Text style={[styles.heading, { color: colors.tertiaryText }]}>
        Chats
      </Text>
      <ScrollView
        contentContainerStyle={styles.rows}
        showsVerticalScrollIndicator={false}
      >
        {rooms.map((room) => (
          <ChatRow key={room.id} room={room} />
        ))}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="New group"
          onPress={() => {
            router.push("/new-room");
          }}
          style={({ pressed }) => [
            styles.row,
            { backgroundColor: colors.card, opacity: pressed ? 0.6 : 1 },
          ]}
        >
          <View style={[styles.rowIcon, { backgroundColor: colors.input }]}>
            <Ionicons name="add" size={19} color={colors.accent} />
          </View>
          <View style={styles.rowText}>
            <Text style={[styles.rowLabel, { color: colors.accent }]}>
              New group
            </Text>
          </View>
        </Pressable>
      </ScrollView>
    </View>
  );
}

const CHATS_LIST_MAX_HEIGHT = 216;

const styles = StyleSheet.create({
  section: {
    maxHeight: CHATS_LIST_MAX_HEIGHT,
    gap: 8,
    paddingHorizontal: 16,
  },
  heading: { fontSize: 13, fontWeight: "600", paddingHorizontal: 4 },
  rows: { gap: 6, paddingBottom: 4 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    borderRadius: radii.control,
    borderCurve: "continuous",
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  rowIcon: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: "center",
    justifyContent: "center",
  },
  rowText: { flex: 1, minWidth: 0, gap: 2 },
  rowLabel: { fontSize: 15, fontWeight: "600" },
  rowDetail: { fontSize: 12 },
  rowTime: { fontSize: 12 },
});

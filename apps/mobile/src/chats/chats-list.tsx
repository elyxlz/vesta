import { use } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import {
  directRoomAgent,
  relativeTime,
  roomLabel,
  type AgentRow,
  type Room,
} from "@vesta/core";
import { useAgentVisualStatus } from "@vesta/core/react";
import { AgentOrb } from "@/components/AgentOrb";
import { Text } from "@/components/ui/Typography";
import { ControllerContext } from "@/controller/context";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { radii } from "@/theme/layout";
import { roomTarget } from "./chats-model";

const DIRECT_ORB_SIZE = 40;
const MEMBER_ORB_SIZE = 26;
const CLUSTER_MAX = 3;
const CLUSTER_OVERLAP = -8;

function useAgentRow(name: string | null): AgentRow | null {
  const { agents } = useRoster();
  if (name === null) return null;
  return agents.find((row) => row.name === name) ?? null;
}

// A roster agent's orb; a name the roster lacks holds the slot empty.
function RosterOrb({ agent, size }: { agent: AgentRow | null; size: number }) {
  if (agent === null) return <View style={{ width: size, height: size }} />;
  return (
    <AgentOrb
      name={agent.name}
      status={agent.status}
      activityState={agent.activityState}
      operation={agent.operation}
      booting={agent.booting}
      rateLimited={agent.rateLimited ?? null}
      size={size}
      animated={false}
    />
  );
}

function MemberOrb({ name, size }: { name: string; size: number }) {
  return <RosterOrb agent={useAgentRow(name)} size={size} />;
}

function ChatRow({ room, striped }: { room: Room; striped: boolean }) {
  const router = useRouter();
  const { colors } = usePreferences();
  const label = roomLabel(room);
  const directName = directRoomAgent(room);
  const direct = useAgentRow(directName);
  // The status word the carousel's badge shows, as plain text.
  const { label: status } = useAgentVisualStatus(
    use(ControllerContext),
    direct,
    direct?.activityState ?? "idle",
  );

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Open ${label} chat`}
      onPress={() => {
        router.push(roomTarget(room));
      }}
      style={({ pressed }) => [
        styles.row,
        {
          backgroundColor: striped ? colors.card : "transparent",
          opacity: pressed ? 0.6 : 1,
        },
      ]}
    >
      {directName !== null ? (
        <RosterOrb agent={direct} size={DIRECT_ORB_SIZE} />
      ) : (
        <View style={styles.cluster}>
          {room.agents.slice(0, CLUSTER_MAX).map((name, index) => (
            <View key={name} style={index > 0 ? styles.clusterMember : null}>
              <MemberOrb name={name} size={MEMBER_ORB_SIZE} />
            </View>
          ))}
        </View>
      )}
      <View style={styles.rowText}>
        <Text
          numberOfLines={1}
          style={[styles.rowLabel, { color: colors.text }]}
        >
          {label}
        </Text>
        <Text
          numberOfLines={1}
          style={[styles.rowDetail, { color: colors.tertiaryText }]}
        >
          {directName !== null ? status : room.agents.join(", ")}
        </Text>
      </View>
      {room.lastMessageAt !== null ? (
        <Text style={[styles.rowTime, { color: colors.tertiaryText }]}>
          {relativeTime(room.lastMessageAt)}
        </Text>
      ) : null}
    </Pressable>
  );
}

// Every conversation on the node, busiest first, under the agent row, striped like the backups
// list so neighboring rows read apart; the screen scrolls, so a long list never fights a nested
// scroll view.
export function ChatsList() {
  const { rooms } = useRoster();
  return (
    <View>
      {rooms.map((room, index) => (
        <ChatRow key={room.id} room={room} striped={index % 2 === 0} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    borderRadius: radii.control,
    borderCurve: "continuous",
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  cluster: { flexDirection: "row", alignItems: "center" },
  clusterMember: { marginLeft: CLUSTER_OVERLAP },
  rowText: { flex: 1, minWidth: 0, gap: 2 },
  rowLabel: { fontSize: 15, fontWeight: "600" },
  rowDetail: { fontSize: 12 },
  // Never squeezed by a long room name: the label truncates instead.
  rowTime: { fontSize: 12, flexShrink: 0 },
});

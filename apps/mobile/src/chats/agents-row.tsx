import { Pressable, ScrollView, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { AgentOrb } from "@/components/AgentOrb";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";

const ORB_SIZE = 64;

// Every agent as its orb, the fast way to one agent's own page above the conversation list.
export function AgentsRow() {
  const router = useRouter();
  const { agents } = useRoster();
  const { colors } = usePreferences();

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
    >
      {agents.map((agent) => (
        <Pressable
          key={agent.name}
          accessibilityRole="button"
          accessibilityLabel={`Open ${agent.name}`}
          onPress={() => {
            router.push({
              pathname: "/agent/[name]",
              params: { name: agent.name },
            });
          }}
          style={({ pressed }) => [styles.item, { opacity: pressed ? 0.6 : 1 }]}
        >
          <AgentOrb
            name={agent.name}
            status={agent.status}
            activityState={agent.activityState}
            operation={agent.operation}
            booting={agent.booting}
            rateLimited={agent.rateLimited ?? null}
            size={ORB_SIZE}
          />
          <Text
            family="serif"
            numberOfLines={1}
            style={[styles.name, { color: colors.text }]}
          >
            {agent.name}
          </Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: 18, paddingLeft: 20, paddingRight: 24, paddingVertical: 8 },
  item: { alignItems: "center", gap: 6, width: ORB_SIZE + 16 },
  name: { fontSize: 13, fontWeight: "500" },
});

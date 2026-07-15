import { Pressable, StyleSheet, View } from "react-native";
import { Stack, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import type { AgentActivityState, AgentStatus } from "@/api/types";
import { useAgent } from "@/agent/AgentProvider";
import { AgentOrb } from "@/components/AgentOrb";
import { BootTransitionTarget } from "@/components/BootTransition";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

export function AgentStackHeader({ hidden = false }: { hidden?: boolean }) {
  const router = useRouter();
  const { name, agent, socket } = useAgent();
  const { colors } = usePreferences();
  const status = agent?.status ?? "not_found";
  const openSettings = () =>
    router.push({
      pathname: "/agent/[name]/settings",
      params: { name },
    });

  return (
    <Stack.Screen
      options={{
        title: name,
        headerShown: !hidden,
        headerTransparent: true,
        headerStyle: { backgroundColor: "transparent" },
        headerShadowVisible: false,
        headerBackButtonDisplayMode: "minimal",
        headerTitle: () => (
          <AgentHeaderTitle
            name={name}
            status={status}
            activityState={socket.agentState}
            color={colors.text}
          />
        ),
        unstable_headerRightItems: () => [
          {
            type: "button",
            label: "Settings",
            accessibilityLabel: "Agent settings",
            icon: { type: "sfSymbol", name: "gearshape" },
            tintColor: colors.accent,
            identifier: "agent-settings",
            onPress: openSettings,
          },
        ],
        headerRight: () => (
          <AgentSettingsHeaderButton
            color={colors.accent}
            onPress={openSettings}
          />
        ),
      }}
    />
  );
}

export function AgentHeaderTitle({
  name,
  status,
  activityState,
  color,
}: {
  name: string;
  status: AgentStatus;
  activityState: AgentActivityState;
  color: string;
}) {
  return (
    <View style={styles.title}>
      <BootTransitionTarget
        destination="agent"
        status={status}
        activityState={activityState}
      >
        <AgentOrb
          status={status}
          activityState={activityState}
          size={24}
        />
      </BootTransitionTarget>
      <Text
        family="heading"
        numberOfLines={1}
        style={[styles.name, { color }]}
      >
        {name}
      </Text>
    </View>
  );
}

export function AgentSettingsHeaderButton({
  color,
  onPress,
}: {
  color: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Agent settings"
      hitSlop={10}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        { opacity: pressed ? 0.72 : 1 },
      ]}
    >
      <Ionicons name="settings-outline" size={22} color={color} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  title: {
    maxWidth: 220,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  name: { flexShrink: 1, fontSize: 18, fontWeight: "500" },
  button: {
    width: 42,
    height: 42,
    borderRadius: 21,
    alignItems: "center",
    justifyContent: "center",
  },
});

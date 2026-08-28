import { Pressable, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import Stack from "expo-router/stack";
import { Ionicons } from "@expo/vector-icons";
import type {
  AgentActivityState,
  AgentOperation,
  AgentStatus,
} from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import { AgentOrb } from "@/components/AgentOrb";
import { BootTransitionTarget } from "@/components/BootTransition";
import { GlassSurface } from "@/components/ui/glass-surface";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

const IS_IOS = process.env.EXPO_OS === "ios";

export function AgentStackHeader({ hidden = false }: { hidden?: boolean }) {
  const router = useRouter();
  const { name, agent, activityState } = useAgent();
  const { colors } = usePreferences();
  const status = agent?.status ?? "not_found";
  const operation = agent?.operation ?? null;
  const booting = agent?.booting;
  const openSettings = () =>
    router.push({
      pathname: "/agent/[name]/settings",
      params: { name },
    });
  const goHome = () => router.dismissTo("/");

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: !hidden,
          headerTransparent: true,
          headerStyle: { backgroundColor: "transparent" },
          headerShadowVisible: false,
          headerBackButtonDisplayMode: "minimal",
          headerTitleAlign: "center",
          headerLeft: IS_IOS
            ? undefined
            : () => (
                <AgentBackHeaderButton color={colors.text} onPress={goHome} />
              ),
        }}
      />
      <Stack.Title asChild>
        <AgentIsland
          name={name}
          status={status}
          activityState={activityState}
          operation={operation}
          booting={booting}
          color={colors.text}
          onPress={openSettings}
        />
      </Stack.Title>
      {IS_IOS && !hidden ? (
        <Stack.Toolbar placement="left">
          <Stack.Toolbar.Button
            accessibilityLabel="Back to agents"
            icon="chevron.backward"
            tintColor={colors.text}
            onPress={goHome}
          />
        </Stack.Toolbar>
      ) : null}
    </>
  );
}

export function AgentIsland({
  name,
  status,
  activityState,
  operation,
  booting = false,
  color,
  onPress,
}: {
  name: string;
  status: AgentStatus;
  activityState: AgentActivityState;
  operation: AgentOperation | null;
  booting?: boolean;
  color: string;
  onPress: () => void;
}) {
  const content = (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Agent settings"
      onPress={onPress}
      style={({ pressed }) => [
        styles.titleContent,
        { opacity: pressed ? 0.72 : 1 },
      ]}
    >
      <BootTransitionTarget
        destination="agent"
        status={status}
        activityState={activityState}
      >
        <AgentOrb
          status={status}
          activityState={activityState}
          operation={operation}
          booting={booting}
          size={24}
        />
      </BootTransitionTarget>
      <Text family="serif" numberOfLines={1} style={[styles.name, { color }]}>
        {name}
      </Text>
    </Pressable>
  );

  return (
    <GlassSurface style={styles.titlePill}>
      {content}
    </GlassSurface>
  );
}

function AgentBackHeaderButton({
  color,
  onPress,
}: {
  color: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Back to agents"
      hitSlop={10}
      onPress={onPress}
      style={({ pressed }) => [styles.button, { opacity: pressed ? 0.72 : 1 }]}
    >
      <Ionicons name="chevron-back" size={25} color={color} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  titlePill: {
    alignSelf: "center",
    maxWidth: 220,
    borderRadius: radii.pill,
    borderCurve: "continuous",
    overflow: "hidden",
  },
  titleContent: {
    minHeight: 42,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
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

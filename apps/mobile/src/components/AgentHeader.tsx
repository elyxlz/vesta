import { Pressable, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import Stack from "expo-router/stack";
import { Ionicons } from "@expo/vector-icons";
import { GlassView, isGlassEffectAPIAvailable } from "expo-glass-effect";
import type { AgentActivityState, AgentStatus } from "@/api/types";
import { useAgent } from "@/agent/AgentProvider";
import { AgentOrb } from "@/components/AgentOrb";
import { BootTransitionTarget } from "@/components/BootTransition";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

const IS_IOS = process.env.EXPO_OS === "ios";

export function AgentStackHeader({ hidden = false }: { hidden?: boolean }) {
  const router = useRouter();
  const { name, agent, socket } = useAgent();
  const { colors, dark } = usePreferences();
  const status = agent?.status ?? "not_found";
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
        <AgentHeaderTitle
          name={name}
          status={status}
          activityState={socket.agentState}
          color={colors.text}
          dark={dark}
          fallbackColor={colors.elevated}
          borderColor={colors.border}
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

export function AgentHeaderTitle({
  name,
  status,
  activityState,
  color,
  dark,
  fallbackColor,
  borderColor,
  onPress,
}: {
  name: string;
  status: AgentStatus;
  activityState: AgentActivityState;
  color: string;
  dark: boolean;
  fallbackColor: string;
  borderColor: string;
  onPress: () => void;
}) {
  const nameContent = (
    <View style={styles.nameContent}>
      <Text family="heading" numberOfLines={1} style={[styles.name, { color }]}>
        {name}
      </Text>
    </View>
  );

  const namePill = isGlassEffectAPIAvailable() ? (
    <GlassView
      glassEffectStyle="regular"
      colorScheme={dark ? "dark" : "light"}
      isInteractive
      style={styles.namePill}
    >
      {nameContent}
    </GlassView>
  ) : (
    <View
      style={[
        styles.namePill,
        styles.titleFallback,
        { backgroundColor: fallbackColor, borderColor },
      ]}
    >
      {nameContent}
    </View>
  );

  return (
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
        <AgentOrb status={status} activityState={activityState} size={28} />
      </BootTransitionTarget>
      {namePill}
    </Pressable>
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
  namePill: {
    maxWidth: 190,
    borderRadius: radii.pill,
    overflow: "hidden",
  },
  titleFallback: {
    borderWidth: StyleSheet.hairlineWidth,
  },
  titleContent: {
    height: 50,
    maxWidth: 220,
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
    paddingHorizontal: 8,
  },
  nameContent: {
    minHeight: 20,
    justifyContent: "center",
    paddingHorizontal: 10,
    paddingVertical: 2,
  },
  name: {
    flexShrink: 1,
    fontSize: 13,
    lineHeight: 16,
    fontWeight: "500",
  },
  button: {
    width: 42,
    height: 42,
    borderRadius: 21,
    alignItems: "center",
    justifyContent: "center",
  },
});

import Stack from "expo-router/stack";
import { AgentProvider } from "@/agent/AgentProvider";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { fontNames } from "@/theme/typography";

export default function AgentLayout() {
  const { colors } = usePreferences();

  return (
    <AgentProvider>
      <Stack
        screenOptions={{
          contentStyle: { backgroundColor: colors.background },
          headerTransparent: true,
          headerStyle: { backgroundColor: "transparent" },
          headerTintColor: colors.text,
          headerTitleStyle: {
            fontFamily: fontNames.heading.native["500"],
            fontSize: 24,
            fontWeight: "500",
          },
          headerShadowVisible: false,
          headerBackButtonDisplayMode: "minimal",
        }}
      >
        <Stack.Screen name="index" />
        <Stack.Screen name="settings" options={{ headerTitle: "" }} />
        <Stack.Screen name="logs" />
        <Stack.Screen name="notifications" />
        <Stack.Screen name="file" />
        <Stack.Screen name="details/[section]" />
      </Stack>
    </AgentProvider>
  );
}

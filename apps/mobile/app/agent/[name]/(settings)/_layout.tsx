import Stack from "expo-router/stack";
import { ProviderDraftProvider } from "@/agent/settings/provider-draft";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { headerTitleStyle } from "@/theme/sheets";

// Direct links enter the same modal stack as navigation from Settings.
export const unstable_settings = { anchor: "settings" };

export default function AgentSettingsLayout() {
  const { colors } = usePreferences();
  const android = process.env.EXPO_OS === "android";
  return (
    <ProviderDraftProvider>
      <Stack
        screenOptions={{
          presentation: "card",
          contentStyle: { backgroundColor: colors.background },
          headerShown: !android,
          headerTransparent: true,
          headerStyle: { backgroundColor: "transparent" },
          headerTintColor: colors.text,
          headerTitleStyle,
          headerTitleAlign: "center",
          headerShadowVisible: false,
          headerBackButtonDisplayMode: "minimal",
        }}
      >
        <Stack.Screen name="settings" options={{ title: "Settings" }} />
        <Stack.Screen name="details/[section]" />
        <Stack.Screen name="logs" />
        <Stack.Screen name="notifications" />
        <Stack.Screen name="file" />
        <Stack.Screen name="provider/choose" />
        <Stack.Screen name="provider/sign-in" />
        <Stack.Screen name="provider/model" />
        <Stack.Screen name="provider/context" />
      </Stack>
    </ProviderDraftProvider>
  );
}

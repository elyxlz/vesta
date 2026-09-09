import Stack from "expo-router/stack";
import { AgentProvider } from "@/agent/AgentProvider";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { formSheetCorners, headerTitleStyle } from "@/theme/sheets";

export const unstable_settings = { anchor: "index" };

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
          headerTitleStyle,
          headerShadowVisible: false,
          headerBackButtonDisplayMode: "minimal",
        }}
      >
        <Stack.Screen name="index" />
        <Stack.Screen
          name="(settings)"
          options={{
            // The modal owns every settings route, including direct links.
            headerShown: false,
            presentation: "formSheet",
            ...formSheetCorners,
            sheetAllowedDetents: [1],
            sheetGrabberVisible: false,
            sheetExpandsWhenScrolledToEdge: false,
            contentStyle: { backgroundColor: colors.background },
          }}
        />
      </Stack>
    </AgentProvider>
  );
}

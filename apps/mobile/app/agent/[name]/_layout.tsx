import Stack from "expo-router/stack";
import { AgentProvider } from "@/agent/AgentProvider";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { fullSheetOptions, stackHeaderOptions } from "@/theme/sheets";

export const unstable_settings = { anchor: "index" };

export default function AgentLayout() {
  const { colors } = usePreferences();

  return (
    <AgentProvider>
      <Stack screenOptions={stackHeaderOptions(colors)}>
        <Stack.Screen name="index" />
        <Stack.Screen
          name="(settings)"
          options={{
            // The modal owns every settings route, including direct links.
            ...fullSheetOptions(colors),
            headerShown: false,
          }}
        />
      </Stack>
    </AgentProvider>
  );
}

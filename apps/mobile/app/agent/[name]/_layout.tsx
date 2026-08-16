import Stack from "expo-router/stack";
import { AgentProvider } from "@/agent/AgentProvider";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { formSheetCorners } from "@/theme/sheets";
import { fontNames } from "@/theme/typography";

// iOS presents logs and notifications sheet-like on its own, because they
// push from the settings form sheet's modal context; Android has no such
// inheritance, so the sheet presentation is spelled out there.
const androidSheetOptions =
  process.env.EXPO_OS === "android"
    ? {
        presentation: "formSheet" as const,
        ...formSheetCorners,
        sheetAllowedDetents: [1],
        sheetGrabberVisible: false,
        sheetExpandsWhenScrolledToEdge: false,
      }
    : {};

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
        <Stack.Screen
          name="settings"
          options={{
            title: "Settings",
            headerTitleAlign: "center",
            presentation: "formSheet",
            ...formSheetCorners,
            sheetAllowedDetents: [1],
            sheetGrabberVisible: false,
            sheetExpandsWhenScrolledToEdge: false,
            contentStyle: { backgroundColor: colors.background },
          }}
        />
        <Stack.Screen name="logs" options={androidSheetOptions} />
        <Stack.Screen name="notifications" options={androidSheetOptions} />
        <Stack.Screen name="file" />
        <Stack.Screen name="details/[section]" />
      </Stack>
    </AgentProvider>
  );
}

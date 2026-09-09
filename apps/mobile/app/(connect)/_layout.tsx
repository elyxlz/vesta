import Stack from "expo-router/stack";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { formSheetCorners, headerTitleStyle } from "@/theme/sheets";

// Keep the connection landing page behind cold-linked authentication sheets.
// The group is pathless: existing /connect-link and /scan URLs stay valid.
export const unstable_settings = { anchor: "connect" };

export default function ConnectLayout() {
  const { colors } = usePreferences();
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        presentation: "formSheet",
        ...formSheetCorners,
        sheetAllowedDetents: "fitToContents",
        contentStyle: { backgroundColor: colors.card },
        headerTransparent: true,
        headerTintColor: colors.text,
        headerTitleStyle,
        headerShadowVisible: false,
      }}
    >
      <Stack.Screen
        name="connect"
        options={{
          presentation: "card",
          contentStyle: { backgroundColor: colors.background },
        }}
      />
      <Stack.Screen
        name="connect-actions"
        options={{
          sheetGrabberVisible: false,
          sheetLargestUndimmedDetentIndex: "last",
          gestureEnabled: false,
        }}
      />
      <Stack.Screen
        name="connect-link"
        options={{ sheetGrabberVisible: true }}
      />
      <Stack.Screen
        name="recent-gateways"
        options={{ sheetGrabberVisible: true }}
      />
      <Stack.Screen
        name="scan"
        options={{
          title: "",
          headerShown: process.env.EXPO_OS === "ios",
          headerTitleAlign: "center",
          // Android can measure a sheet pushed above another form sheet
          // against the entire window, including the status bar. Reserve a
          // visible backdrop so the scanner's close control stays below it.
          sheetAllowedDetents: process.env.EXPO_OS === "android" ? [0.92] : [1],
          sheetGrabberVisible: false,
          sheetExpandsWhenScrolledToEdge: false,
          contentStyle: { backgroundColor: colors.background },
        }}
      />
    </Stack>
  );
}

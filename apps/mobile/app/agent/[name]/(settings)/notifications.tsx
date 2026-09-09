import { useRouter } from "expo-router";
import Stack from "expo-router/stack";
import { Ionicons } from "@expo/vector-icons";
import { SheetTitle } from "@/components/sheet-title";
import NotificationsPage from "@/agent/NotificationsPage";
import { useAgent } from "@/agent/AgentProvider";
import { sectionTitle } from "@/agent/settings/sections-model";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { SheetChrome } from "@/components/sheet-chrome";
import { usePreferences } from "@/preferences/PreferencesProvider";

const IS_IOS = process.env.EXPO_OS === "ios";

function NotificationsContent() {
  const router = useRouter();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const openRules = () =>
    router.push({
      pathname: "/agent/[name]/details/[section]",
      params: { name, section: "notifications" },
    });
  return (
    <>
      {IS_IOS ? (
        <>
          <SheetTitle>Notifications</SheetTitle>
          <NativeSheetCloseButton accessibilityLabel="Close notifications" />
          <Stack.Toolbar placement="right">
            <Stack.Toolbar.Button
              accessibilityLabel={sectionTitle("notifications")}
              icon="slider.horizontal.3"
              separateBackground
              tintColor={colors.text}
              onPress={openRules}
            />
          </Stack.Toolbar>
        </>
      ) : null}
      <SheetChrome
        title="Notifications"
        closeLabel="Close notifications"
        action={{
          accessibilityLabel: sectionTitle("notifications"),
          onPress: openRules,
          icon: (
            <Ionicons name="options-outline" size={24} color={colors.text} />
          ),
        }}
      />
      <NotificationsPage presentation="standalone" />
    </>
  );
}

export default function NotificationsScreen() {
  return <NotificationsContent />;
}

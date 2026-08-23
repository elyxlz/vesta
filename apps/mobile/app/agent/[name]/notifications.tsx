import { useRouter } from "expo-router";
import Stack from "expo-router/stack";
import { SheetTitle } from "@/components/sheet-title";
import NotificationsPage from "@/agent/NotificationsPage";
import { useAgent } from "@/agent/AgentProvider";
import { sectionTitle } from "@/agent/settings/sections-model";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { SheetChrome } from "@/components/sheet-chrome";
import { usePreferences } from "@/preferences/PreferencesProvider";
import tuneIcon from "../../../assets/toolbar-icons/tune.xml";

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
      <SheetTitle>Notifications</SheetTitle>
      <NativeSheetCloseButton accessibilityLabel="Close notifications" />
      <Stack.Toolbar placement="right">
        <Stack.Toolbar.Button
          accessibilityLabel={sectionTitle("notifications")}
          icon={IS_IOS ? "slider.horizontal.3" : tuneIcon}
          separateBackground
          tintColor={colors.text}
          onPress={openRules}
        />
      </Stack.Toolbar>
      <SheetChrome title="Notifications" closeLabel="Close notifications" />
      <NotificationsPage presentation="standalone" />
    </>
  );
}

export default function NotificationsScreen() {
  return <NotificationsContent />;
}

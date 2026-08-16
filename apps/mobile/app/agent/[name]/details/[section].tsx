import { StyleSheet } from "react-native";
import { useLocalSearchParams } from "expo-router";
import Stack from "expo-router/stack";
import { BackupsSection } from "@/agent/settings/BackupsSection";
import { FilesSection } from "@/agent/settings/FilesSection";
import { GeneralSection } from "@/agent/settings/GeneralSection";
import { HostAccessSection } from "@/agent/settings/HostAccessSection";
import { NotificationsSection } from "@/agent/settings/NotificationsSection";
import { ProviderSection } from "@/agent/settings/ProviderSection";
import { VoiceSection } from "@/agent/settings/VoiceSection";
import { Screen } from "@/components/layout/Screen";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

const titles: Record<string, string> = {
  general: "General",
  provider: "Provider and model",
  voice: "Voice",
  notifications: "Notification rules",
  files: "Files",
  "host-access": "Host access",
  backups: "Backups",
};

// Agent settings on Android carry only the simple critical controls, so a
// deep link into a hidden section lands on the fallback, never a broken page.
const SHOWS_ADVANCED_SECTIONS = process.env.EXPO_OS === "ios";
const advancedSections = new Set([
  "provider",
  "voice",
  "notifications",
  "files",
  "host-access",
  "backups",
]);

function AgentDetailContent() {
  const parameters = useLocalSearchParams<{ section?: string }>();
  const { colors } = usePreferences();
  const section =
    typeof parameters.section === "string" ? parameters.section : "general";
  const title = titles[section] ?? "Settings";
  const content = (() => {
    if (!SHOWS_ADVANCED_SECTIONS && advancedSections.has(section)) {
      return (
        <Text style={[styles.unknown, { color: colors.secondaryText }]}>
          This settings section is not available on Android yet.
        </Text>
      );
    }
    if (section === "general") return <GeneralSection />;
    if (section === "provider") return <ProviderSection />;
    if (section === "voice") return <VoiceSection />;
    if (section === "notifications") return <NotificationsSection />;
    if (section === "files") return <FilesSection />;
    if (section === "host-access") return <HostAccessSection />;
    if (section === "backups") return <BackupsSection />;
    return (
      <Text style={[styles.unknown, { color: colors.secondaryText }]}>
        This settings section does not exist.
      </Text>
    );
  })();
  return (
    <>
      <Stack.Title>{title}</Stack.Title>
      <NativeSheetCloseButton accessibilityLabel={`Close ${title}`} />
      <Screen contentStyle={styles.content}>{content}</Screen>
    </>
  );
}

export default function AgentDetailScreen() {
  return <AgentDetailContent />;
}

const styles = StyleSheet.create({
  content: { paddingBottom: 80 },
  unknown: { textAlign: "center", padding: 30 },
});

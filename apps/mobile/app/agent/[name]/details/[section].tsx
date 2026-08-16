import { StyleSheet } from "react-native";
import { useLocalSearchParams } from "expo-router";
import Stack from "expo-router/stack";
import { BackupsSection } from "@/agent/settings/BackupsSection";
import { FilesSection } from "@/agent/settings/FilesSection";
import { GeneralSection } from "@/agent/settings/GeneralSection";
import { HostAccessSection } from "@/agent/settings/HostAccessSection";
import { NotificationsSection } from "@/agent/settings/NotificationsSection";
import { ProviderSection } from "@/agent/settings/ProviderSection";
import {
  sectionAvailability,
  sectionTitle,
} from "@/agent/settings/sections-model";
import { VoiceSection } from "@/agent/settings/VoiceSection";
import { Screen } from "@/components/layout/Screen";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

export default function AgentDetailScreen() {
  const parameters = useLocalSearchParams<{ section?: string }>();
  const { colors } = usePreferences();
  const section =
    typeof parameters.section === "string" ? parameters.section : "general";
  const title = sectionTitle(section);
  const content = (() => {
    if (sectionAvailability(section) === "hidden") {
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

const styles = StyleSheet.create({
  content: { paddingBottom: 80 },
  unknown: { textAlign: "center", padding: 30 },
});

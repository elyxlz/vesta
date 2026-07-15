import { StyleSheet } from "react-native";
import { Stack, useLocalSearchParams } from "expo-router";
import { AgentProvider } from "@/agent/AgentProvider";
import { BackupsSection } from "@/agent/settings/BackupsSection";
import { FilesSection } from "@/agent/settings/FilesSection";
import { GeneralSection } from "@/agent/settings/GeneralSection";
import { HostAccessSection } from "@/agent/settings/HostAccessSection";
import { NotificationsSection } from "@/agent/settings/NotificationsSection";
import { ProviderSection } from "@/agent/settings/ProviderSection";
import { VoiceSection } from "@/agent/settings/VoiceSection";
import { Screen } from "@/components/layout/Screen";
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

function AgentDetailContent() {
  const parameters = useLocalSearchParams<{ section?: string }>();
  const { colors } = usePreferences();
  const section = typeof parameters.section === "string" ? parameters.section : "general";
  const title = titles[section] ?? "Settings";
  const content = (() => {
    if (section === "general") return <GeneralSection />;
    if (section === "provider") return <ProviderSection />;
    if (section === "voice") return <VoiceSection />;
    if (section === "notifications") return <NotificationsSection />;
    if (section === "files") return <FilesSection />;
    if (section === "host-access") return <HostAccessSection />;
    if (section === "backups") return <BackupsSection />;
    return <Text style={[styles.unknown, { color: colors.secondaryText }]}>This settings section does not exist.</Text>;
  })();
  return (
    <>
      <Stack.Screen options={{ title }} />
      <Screen contentStyle={styles.content}>{content}</Screen>
    </>
  );
}

export default function AgentDetailScreen() {
  return (
    <AgentProvider>
      <AgentDetailContent />
    </AgentProvider>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 80 },
  unknown: { textAlign: "center", padding: 30 },
});

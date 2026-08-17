import type { ComponentType } from "react";
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
  findSection,
  sectionTitle,
  type AgentSettingsSectionKey,
} from "@/agent/settings/sections-model";
import { VoiceSection } from "@/agent/settings/VoiceSection";
import { Screen } from "@/components/layout/Screen";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { SheetChrome } from "@/components/sheet-chrome";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

const SECTION_CONTENT: Record<AgentSettingsSectionKey, ComponentType> = {
  general: GeneralSection,
  provider: ProviderSection,
  voice: VoiceSection,
  notifications: NotificationsSection,
  files: FilesSection,
  "host-access": HostAccessSection,
  backups: BackupsSection,
};

export default function AgentDetailScreen() {
  const parameters = useLocalSearchParams<{ section?: string }>();
  const { colors } = usePreferences();
  const section =
    typeof parameters.section === "string" ? parameters.section : "general";
  const title = sectionTitle(section);
  const found = findSection(section);
  const Section = found ? SECTION_CONTENT[found.key] : null;
  return (
    <>
      <Stack.Title>{title}</Stack.Title>
      <NativeSheetCloseButton accessibilityLabel={`Close ${title}`} />
      <SheetChrome title={title} closeLabel={`Close ${title}`} />
      <Screen contentStyle={styles.content}>
        {Section ? (
          <Section />
        ) : (
          <Text style={[styles.unknown, { color: colors.secondaryText }]}>
            This settings section does not exist.
          </Text>
        )}
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 80 },
  unknown: { textAlign: "center", padding: 30 },
});

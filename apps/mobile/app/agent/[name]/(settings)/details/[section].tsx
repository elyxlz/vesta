import { useEffect, type ComponentType } from "react";
import { StyleSheet } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SheetTitle } from "@/components/sheet-title";
import { BackupsSection } from "@/agent/settings/BackupsSection";
import { FilesSection } from "@/agent/settings/FilesSection";
import { RenameAgentPanel } from "@/agent/settings/rename-agent-panel";
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
  name: RenameAgentPanel,
  provider: ProviderSection,
  voice: VoiceSection,
  notifications: NotificationsSection,
  files: FilesSection,
  "host-access": HostAccessSection,
  backups: BackupsSection,
};

export default function AgentDetailScreen() {
  const parameters = useLocalSearchParams<{ name: string; section?: string }>();
  const router = useRouter();
  const { colors } = usePreferences();
  const section =
    typeof parameters.section === "string" ? parameters.section : "general";
  // General was folded into Settings. Dismiss to its existing anchor rather
  // than creating a second Settings panel behind this legacy deep link.
  useEffect(() => {
    if (section === "general") {
      router.dismissTo({
        pathname: "/agent/[name]/settings",
        params: { name: parameters.name },
      });
    }
  }, [parameters.name, router, section]);
  if (section === "general") return null;
  const title = sectionTitle(section);
  const found = findSection(section);
  const Section = found ? SECTION_CONTENT[found.key] : null;
  return (
    <>
      {process.env.EXPO_OS === "ios" ? (
        <>
          <SheetTitle>{title}</SheetTitle>
          <NativeSheetCloseButton accessibilityLabel={`Close ${title}`} />
        </>
      ) : null}
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

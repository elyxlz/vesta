import { StyleSheet } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useVoiceSettings } from "@/agent/settings/voice-actions";
import { VoiceOptionList } from "@/agent/settings/voice-option-list";
import {
  findSetting,
  parseSettingSection,
} from "@/agent/settings/voice-settings-model";
import { Screen } from "@/components/layout/Screen";
import { SheetChrome } from "@/components/sheet-chrome";
import { SheetTitle } from "@/components/sheet-title";
import { FormSectionSkeleton } from "@/components/ui/form-section-skeleton";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

const IS_IOS = process.env.EXPO_OS === "ios";

// The options of one select setting of the voice service, named by its section and its key.
// iOS draws the title and the back chevron natively; Android sheets have no native header, so
// SheetChrome stands in.
export default function VoiceSelectScreen() {
  const parameters = useLocalSearchParams<{
    section?: string;
    setting?: string;
  }>();
  const { colors } = usePreferences();
  const { settings } = useVoiceSettings();
  const section = parseSettingSection(parameters.section);
  const setting =
    settings.data && section && typeof parameters.setting === "string"
      ? findSetting(settings.data, section, parameters.setting)
      : null;
  const title = setting?.label ?? "Voice";
  return (
    <>
      {IS_IOS ? <SheetTitle>{title}</SheetTitle> : null}
      <SheetChrome title={title} closeLabel="Back" />
      <Screen contentStyle={styles.content}>
        {setting && section ? (
          <VoiceOptionList setting={setting} section={section} />
        ) : settings.isLoading ? (
          <FormSectionSkeleton rows={6} label="Loading options" />
        ) : (
          <Text style={[styles.unknown, { color: colors.secondaryText }]}>
            This voice setting does not exist.
          </Text>
        )}
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  content: { gap: 24, paddingBottom: 80 },
  unknown: { textAlign: "center", padding: 30 },
});

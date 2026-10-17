import { useState } from "react";
import { useRouter } from "expo-router";
import Stack from "expo-router/stack";
import * as Haptics from "expo-haptics";
import type { SettingDef } from "@vesta/core";
import { useVoiceChange } from "@/agent/settings/voice-actions";
import {
  filterOptions,
  type SettingSection,
} from "@/agent/settings/voice-settings-model";
import { LoadingSpinner } from "@/components/loading-spinner";
import { Field, FormRow, FormSection } from "@/components/ui/Form";
import { usePreferences } from "@/preferences/PreferencesProvider";

const IS_IOS = process.env.EXPO_OS === "ios";

// Every option of one select setting, searchable from the native header search bar on iOS and
// from a field on Android. A tap saves the option and returns to the voice page; a spinner
// marks the one being saved, so every other row waits.
export function VoiceOptionList({
  setting,
  section,
}: {
  setting: SettingDef;
  section: SettingSection;
}) {
  const router = useRouter();
  const { colors } = usePreferences();
  const change = useVoiceChange();
  const [query, setQuery] = useState("");
  const options = filterOptions(setting.options ?? [], query);
  const selected = typeof setting.value === "string" ? setting.value : null;
  const pending =
    change.isPending && change.variables.type === "setting"
      ? change.variables.value
      : null;

  const pick = (value: string) => {
    void Haptics.selectionAsync();
    if (value === selected) {
      router.back();
      return;
    }
    change.mutate(
      { type: "setting", domain: section, key: setting.key, value },
      { onSuccess: () => router.back() },
    );
  };

  return (
    <>
      {IS_IOS ? (
        <Stack.SearchBar
          placeholder="Search"
          autoCapitalize="none"
          hideWhenScrolling={false}
          onChangeText={(event) => setQuery(event.nativeEvent.text)}
          onCancelButtonPress={() => setQuery("")}
        />
      ) : (
        <Field
          placeholder="Search"
          value={query}
          onChangeText={setQuery}
          autoCapitalize="none"
          autoCorrect={false}
        />
      )}
      <FormSection footer={setting.description}>
        {options.length === 0 ? <FormRow label="No matches" /> : null}
        {options.map((option) => (
          <FormRow
            key={option.value}
            label={option.label}
            detail={option.description}
            selected={pending === null ? option.value === selected : false}
            trailing={
              pending === option.value ? (
                <LoadingSpinner color={colors.secondaryText} />
              ) : undefined
            }
            onPress={pending === null ? () => pick(option.value) : undefined}
          />
        ))}
      </FormSection>
    </>
  );
}

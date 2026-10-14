import { useState } from "react";
import { Alert, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import type { SettingDef } from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import {
  ALERT_MAX_OPTIONS,
  formatNumber,
  numberRange,
  numberValue,
  selectedOptionLabel,
  type SettingSection,
} from "@/agent/settings/voice-settings-model";
import { Button } from "@/components/ui/Button";
import { Field, FormRow, SwitchRow } from "@/components/ui/Form";
import { Slider } from "@/components/ui/Slider";

// Saves one value of a setting. `onSettled` runs when the save is over: the page then holds the
// saved value, or the voice service refused it.
type SaveSetting = (
  section: SettingSection,
  key: string,
  value: unknown,
  onSettled?: () => void,
) => void;

interface SettingProps {
  setting: SettingDef;
  section: SettingSection;
  onSave: SaveSetting;
}

// A short list is a system alert; a long one, such as the voices of a provider, is a screen
// with a search field.
function SelectSetting({ setting, section, onSave }: SettingProps) {
  const router = useRouter();
  const { name } = useAgent();
  const options = setting.options ?? [];
  const choose = () => {
    if (options.length > ALERT_MAX_OPTIONS) {
      router.push({
        pathname: "/agent/[name]/voice/select",
        params: { name, section, setting: setting.key },
      });
      return;
    }
    Alert.alert(setting.label, setting.description, [
      ...options.map((option) => ({
        text: option.label,
        onPress: () => onSave(section, setting.key, option.value),
      })),
      { text: "Cancel", style: "cancel" },
    ]);
  };
  return (
    <FormRow
      label={setting.label}
      detail={setting.description}
      value={selectedOptionLabel(setting)}
      onPress={choose}
    />
  );
}

// The slider shows each value under the finger and saves the one the user lets go on.
function NumberSetting({ setting, section, onSave }: SettingProps) {
  const range = numberRange(setting);
  const saved = numberValue(setting);
  // The value in the user's hand, keyed by the saved value it started from, so a saved value
  // that changes shows through. It is dropped when its save is over, unless a newer one is held.
  const [edit, setEdit] = useState<{ base: number; value: number } | null>(
    null,
  );
  const value = edit !== null && edit.base === saved ? edit.value : saved;
  const shown = formatNumber(setting, value);
  return (
    <View>
      <FormRow
        label={setting.label}
        detail={setting.description}
        value={shown}
      />
      <Slider
        accessibilityLabel={setting.label}
        valueText={shown}
        value={value}
        min={range.min}
        max={range.max}
        step={range.step}
        onChange={(next) => setEdit({ base: saved, value: next })}
        onCommit={(next) => {
          if (next === saved) return;
          onSave(section, setting.key, next, () =>
            setEdit((held) => (held?.value === next ? null : held)),
          );
        }}
      />
    </View>
  );
}

// A text value, such as the address of a speech model on the agent's own machine.
function TextSetting({
  setting,
  section,
  onSave,
  busy,
}: SettingProps & { busy: boolean }) {
  const saved = typeof setting.value === "string" ? setting.value : "";
  // The text in the user's hand, keyed by the saved value it started from, so a saved value
  // that changes shows through.
  const [edit, setEdit] = useState<{ base: string; value: string } | null>(
    null,
  );
  const draft = edit !== null && edit.base === saved ? edit.value : saved;
  return (
    <View style={styles.textSetting}>
      <Field
        label={setting.label}
        description={setting.description}
        value={draft}
        onChangeText={(value) => setEdit({ base: saved, value })}
        autoCapitalize="none"
        autoCorrect={false}
      />
      <Button
        variant="secondary"
        disabled={busy || !draft.trim()}
        onPress={() => onSave(section, setting.key, draft.trim())}
      >
        Apply
      </Button>
    </View>
  );
}

export function VoiceSetting({
  setting,
  section,
  onSave,
  busy,
}: SettingProps & { busy: boolean }) {
  if (setting.type === "bool") {
    return (
      <SwitchRow
        label={setting.label}
        detail={setting.description}
        value={Boolean(setting.value)}
        onValueChange={(value) => onSave(section, setting.key, value)}
      />
    );
  }
  if (setting.type === "select") {
    return (
      <SelectSetting setting={setting} section={section} onSave={onSave} />
    );
  }
  if (setting.type === "text") {
    return (
      <TextSetting
        setting={setting}
        section={section}
        onSave={onSave}
        busy={busy}
      />
    );
  }
  return <NumberSetting setting={setting} section={section} onSave={onSave} />;
}

const styles = StyleSheet.create({
  textSetting: { gap: 8 },
});

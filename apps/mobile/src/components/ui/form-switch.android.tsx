import { StyleSheet } from "react-native";
import { Host, Switch } from "@expo/ui/jetpack-compose";
import type { FormSwitchProps } from "@/components/ui/form-switch.types";
import { usePreferences } from "@/preferences/PreferencesProvider";

// Android renders the Material 3 Compose switch, colored to match the iOS
// pairing: accent track with a white thumb when on.
export function FormSwitch({
  value,
  onValueChange,
  disabled = false,
}: FormSwitchProps) {
  const preferences = usePreferences();
  const { colors } = preferences;
  return (
    <Host
      colorScheme={preferences.dark ? "dark" : "light"}
      seedColor={colors.accent}
      style={styles.host}
    >
      <Switch
        value={value}
        enabled={!disabled}
        onCheckedChange={onValueChange}
        colors={{
          checkedTrackColor: colors.accent,
          checkedThumbColor: "#ffffff",
          uncheckedTrackColor: colors.input,
          uncheckedBorderColor: colors.border,
          uncheckedThumbColor: colors.secondaryText,
        }}
      />
    </Host>
  );
}

const styles = StyleSheet.create({
  host: { width: 52, height: 32 },
});

import { Switch } from "react-native";
import type { FormSwitchProps } from "@/components/ui/form-switch.types";
import { usePreferences } from "@/preferences/PreferencesProvider";

// iOS renders the native UISwitch.
export function FormSwitch({
  value,
  onValueChange,
  disabled = false,
}: FormSwitchProps) {
  const { colors } = usePreferences();
  return (
    <Switch
      value={value}
      onValueChange={onValueChange}
      disabled={disabled}
      trackColor={{ false: colors.input, true: colors.accent }}
    />
  );
}

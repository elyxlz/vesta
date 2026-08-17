import { StyleSheet } from "react-native";
import {
  AlertDialog,
  Column,
  Host,
  RadioButton,
  Row,
  Text,
  TextButton,
} from "@expo/ui/jetpack-compose";
import {
  fillMaxWidth,
  padding,
  selectable,
  selectableGroup,
} from "@expo/ui/jetpack-compose/modifiers";
import type { OptionPickerProps } from "@/components/option-picker.types";
import { usePreferences } from "@/preferences/PreferencesProvider";

// A Material 3 radio-list dialog. The Compose dialog floats in its own
// window, so the zero-size Host never affects the caller's layout.
export function OptionPicker<T extends string>({
  visible,
  title,
  message,
  options,
  selectedValue,
  onSelect,
  onDismiss,
}: OptionPickerProps<T>) {
  const preferences = usePreferences();
  if (!visible) return null;

  return (
    <Host
      colorScheme={preferences.dark ? "dark" : "light"}
      seedColor={preferences.colors.accent}
      style={styles.host}
    >
      <AlertDialog onDismissRequest={onDismiss}>
        <AlertDialog.Title>
          <Text>{title}</Text>
        </AlertDialog.Title>
        <AlertDialog.Text>
          <Column modifiers={[fillMaxWidth(), selectableGroup()]}>
            {message ? (
              <Text modifiers={[padding(0, 0, 0, 12)]}>{message}</Text>
            ) : null}
            {options.map((option) => (
              <Row
                key={option.value}
                verticalAlignment="center"
                modifiers={[
                  fillMaxWidth(),
                  selectable(
                    option.value === selectedValue,
                    () => {
                      onSelect(option.value);
                    },
                    "radioButton",
                  ),
                  padding(0, 12, 0, 12),
                ]}
              >
                <RadioButton
                  selected={option.value === selectedValue}
                  onClick={() => {
                    onSelect(option.value);
                  }}
                />
                <Text
                  modifiers={[padding(12, 0, 0, 0)]}
                  style={{ typography: "bodyLarge" }}
                >
                  {option.label}
                </Text>
              </Row>
            ))}
          </Column>
        </AlertDialog.Text>
        <AlertDialog.DismissButton>
          <TextButton onClick={onDismiss}>
            <Text>Cancel</Text>
          </TextButton>
        </AlertDialog.DismissButton>
      </AlertDialog>
    </Host>
  );
}

const styles = StyleSheet.create({
  host: { position: "absolute", width: 0, height: 0 },
});

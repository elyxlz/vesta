import { useEffect, useRef } from "react";
import { Alert } from "react-native";
import type { OptionPickerProps } from "@/components/option-picker.types";

// Bridges the declarative picker API onto the imperative system alert: each
// visible=true transition presents exactly one alert, and exactly one of
// onSelect or onDismiss fires per presentation.
export function OptionPicker<T extends string>({
  visible,
  title,
  message,
  options,
  onSelect,
  onDismiss,
}: OptionPickerProps<T>) {
  const presented = useRef(false);

  useEffect(() => {
    if (!visible) {
      presented.current = false;
      return;
    }
    if (presented.current) return;
    presented.current = true;
    Alert.alert(title, message, [
      ...options.map((option) => ({
        text: option.label,
        onPress: () => onSelect(option.value),
      })),
      { text: "Cancel", style: "cancel" as const, onPress: onDismiss },
    ]);
  }, [visible, title, message, options, onSelect, onDismiss]);

  return null;
}

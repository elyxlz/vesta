import { Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import type { NativeDeleteRowProps } from "./NativeDeleteRow.types";

export function NativeDeleteRow({
  children,
  containerStyle,
  deleteAccessibilityLabel,
  dangerColor,
  disabled = false,
  onDelete,
}: NativeDeleteRowProps) {
  return (
    <View style={containerStyle}>
      {children}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={deleteAccessibilityLabel}
        disabled={disabled}
        hitSlop={8}
        onPress={onDelete}
        style={({ pressed }) => [
          styles.deleteButton,
          { opacity: pressed ? 0.55 : 1 },
        ]}
      >
        <Ionicons name="trash-outline" size={18} color={dangerColor} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  deleteButton: {
    width: 48,
    height: 48,
    alignItems: "center",
    justifyContent: "center",
  },
});

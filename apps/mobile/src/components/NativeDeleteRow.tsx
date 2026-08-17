import { Platform, Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import type { NativeDeleteRowProps } from "./NativeDeleteRow.types";

const RIPPLE_ALPHA_HEX = "2e";

export function NativeDeleteRow({
  children,
  containerStyle,
  deleteAccessibilityLabel,
  dangerColor,
  disabled = false,
  onDelete,
}: NativeDeleteRowProps) {
  const isAndroid = Platform.OS === "android";
  return (
    <View style={containerStyle}>
      {children}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={deleteAccessibilityLabel}
        android_ripple={{
          borderless: true,
          color: `${dangerColor}${RIPPLE_ALPHA_HEX}`,
          radius: 24,
        }}
        disabled={disabled}
        hitSlop={8}
        onPress={onDelete}
        style={({ pressed }) => [
          styles.deleteButton,
          { opacity: pressed && !isAndroid ? 0.55 : 1 },
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

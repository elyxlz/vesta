import type { ComponentProps } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { usePreferences } from "@/preferences/PreferencesProvider";

// The round elevated icon button a screen's header carries on Android; iOS screens use the
// native toolbar instead.
export function HeaderButton({
  accessibilityLabel,
  icon,
  iconSize,
  onPress,
}: {
  accessibilityLabel: string;
  icon: ComponentProps<typeof Ionicons>["name"];
  iconSize: number;
  onPress: () => void;
}) {
  const { colors } = usePreferences();
  return (
    <View style={[styles.button, { backgroundColor: colors.elevated }]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel}
        hitSlop={8}
        onPress={onPress}
        style={({ pressed }) => [
          styles.content,
          { opacity: pressed ? 0.68 : 1 },
        ]}
      >
        <Ionicons name={icon} size={iconSize} color={colors.text} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  button: { width: 40, height: 40, borderRadius: 20, overflow: "hidden" },
  content: { flex: 1, alignItems: "center", justifyContent: "center" },
});

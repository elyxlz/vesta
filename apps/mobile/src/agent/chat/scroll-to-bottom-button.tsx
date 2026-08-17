import { Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { GlassSurface } from "@/components/ui/glass-surface";
import { usePreferences } from "@/preferences/PreferencesProvider";

export function ScrollToBottomButton({ onPress }: { onPress: () => void }) {
  const { colors } = usePreferences();
  return (
    <GlassSurface style={styles.scrollToBottomButton}>
      <Pressable
        accessibilityLabel="Scroll to latest message"
        accessibilityRole="button"
        hitSlop={8}
        onPress={onPress}
        style={({ pressed }) => [
          styles.scrollToBottomPressable,
          { opacity: pressed ? 0.7 : 1 },
        ]}
      >
        <Ionicons name="arrow-down" size={18} color={colors.text} />
      </Pressable>
    </GlassSurface>
  );
}

const styles = StyleSheet.create({
  scrollToBottomButton: {
    width: 34,
    height: 34,
    borderRadius: 17,
    overflow: "hidden",
  },
  scrollToBottomPressable: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
});

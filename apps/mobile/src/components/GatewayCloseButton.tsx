import { Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { GlassView, isGlassEffectAPIAvailable } from "expo-glass-effect";
import { usePreferences } from "@/preferences/PreferencesProvider";

export function GatewayCloseButton({
  color,
  fallbackColor,
  onPress,
}: {
  color: string;
  fallbackColor: string;
  onPress: () => void;
}) {
  const { dark } = usePreferences();
  const content = (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Close"
      hitSlop={12}
      onPress={onPress}
      style={({ pressed }) => [
        styles.closeContent,
        { opacity: pressed ? 0.72 : 1 },
      ]}
    >
      <Ionicons name="close" size={21} color={color} />
    </Pressable>
  );

  if (isGlassEffectAPIAvailable()) {
    return (
      <GlassView
        glassEffectStyle="regular"
        colorScheme={dark ? "dark" : "light"}
        isInteractive
        style={styles.close}
      >
        {content}
      </GlassView>
    );
  }

  return (
    <View style={[styles.close, { backgroundColor: fallbackColor }]}>
      {content}
    </View>
  );
}

const styles = StyleSheet.create({
  close: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignSelf: "center",
    overflow: "hidden",
  },
  closeContent: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
});

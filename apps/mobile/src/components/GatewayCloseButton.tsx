import { Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { GlassView, isGlassEffectAPIAvailable } from "expo-glass-effect";

export function GatewayCloseButton({
  color,
  fallbackColor,
  onPress,
}: {
  color: string;
  fallbackColor: string;
  onPress: () => void;
}) {
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
        colorScheme="light"
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
    overflow: "hidden",
    transform: [{ translateY: 1 }],
  },
  closeContent: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
});

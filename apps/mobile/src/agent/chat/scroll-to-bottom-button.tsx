import { useEffect } from "react";
import { Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import {
  GLASS_TRANSITION_MS,
  GlassSurface,
} from "@/components/ui/glass-surface";
import { usePreferences } from "@/preferences/PreferencesProvider";

export function ScrollToBottomButton({
  visible,
  onPress,
}: {
  visible: boolean;
  onPress: () => void;
}) {
  const { colors } = usePreferences();
  const scale = useSharedValue(visible ? 1 : 0);
  const growStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  useEffect(() => {
    scale.set(withTiming(visible ? 1 : 0, { duration: GLASS_TRANSITION_MS }));
  }, [scale, visible]);

  return (
    <Animated.View
      pointerEvents={visible ? "auto" : "none"}
      style={[styles.growFromBottom, growStyle]}
    >
      <GlassSurface materialized={visible} style={styles.scrollToBottomButton}>
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
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  growFromBottom: { transformOrigin: "bottom center" },
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

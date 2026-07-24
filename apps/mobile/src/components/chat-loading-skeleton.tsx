import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  Easing,
  cancelAnimation,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

const PLACEHOLDER_ROWS = [
  { side: "agent", width: "70%", height: 64 },
  { side: "user", width: "52%", height: 42 },
  { side: "agent", width: "46%", height: 42 },
  { side: "user", width: "64%", height: 58 },
  { side: "agent", width: "76%", height: 78 },
  { side: "user", width: "42%", height: 42 },
  { side: "agent", width: "58%", height: 54 },
  { side: "user", width: "68%", height: 44 },
  { side: "agent", width: "40%", height: 38 },
  { side: "user", width: "55%", height: 32 },
  { side: "agent", width: "62%", height: 38 },
] as const;

export function ChatLoadingSkeleton() {
  const { colors } = usePreferences();
  const reduceMotion = useReducedMotion();
  const opacity = useSharedValue(reduceMotion ? 0.58 : 0.42);
  const pulseStyle = useAnimatedStyle(() => ({ opacity: opacity.value }));

  useEffect(() => {
    cancelAnimation(opacity);
    opacity.set(
      reduceMotion
        ? 0.58
        : withRepeat(
            withTiming(0.76, {
              duration: 800,
              easing: Easing.inOut(Easing.quad),
            }),
            -1,
            true,
          ),
    );

    return () => cancelAnimation(opacity);
  }, [opacity, reduceMotion]);

  return (
    <Animated.View
      accessible
      accessibilityLabel="Loading conversation"
      accessibilityRole="progressbar"
      accessibilityState={{ busy: true }}
      pointerEvents="none"
      style={[styles.skeleton, pulseStyle]}
    >
      <View style={styles.stack}>
        <View
          style={[styles.date, { backgroundColor: colors.input }]}
        />
        {PLACEHOLDER_ROWS.map((row, index) => (
          <View
            key={index}
            style={[
              styles.bubble,
              row.side === "user" ? styles.userBubble : styles.agentBubble,
              {
                width: row.width,
                height: row.height,
                backgroundColor:
                  row.side === "user" ? colors.accent : colors.card,
                borderColor:
                  row.side === "agent" ? colors.border : "transparent",
              },
            ]}
          />
        ))}
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  skeleton: {
    flex: 1,
    overflow: "hidden",
  },
  stack: {
    position: "absolute",
    right: 8,
    bottom: 0,
    left: 8,
    gap: 10,
  },
  date: {
    alignSelf: "center",
    width: 68,
    height: 14,
    borderRadius: 7,
  },
  bubble: {
    borderRadius: radii.bubble,
    borderCurve: "continuous",
  },
  agentBubble: {
    alignSelf: "flex-start",
    borderWidth: StyleSheet.hairlineWidth,
  },
  userBubble: { alignSelf: "flex-end" },
});

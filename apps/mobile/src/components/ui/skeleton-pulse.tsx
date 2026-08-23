import { useEffect, type ReactNode } from "react";
import type { StyleProp, ViewStyle } from "react-native";
import Animated, {
  Easing,
  cancelAnimation,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";

// The breathing container every loading skeleton sits in: one pulse, one
// accessibility announcement, steady when the user prefers reduced motion.
export function SkeletonPulse({
  label,
  style,
  children,
}: {
  label: string;
  style?: StyleProp<ViewStyle>;
  children: ReactNode;
}) {
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
      accessibilityLabel={label}
      accessibilityRole="progressbar"
      accessibilityState={{ busy: true }}
      pointerEvents="none"
      style={[style, pulseStyle]}
    >
      {children}
    </Animated.View>
  );
}

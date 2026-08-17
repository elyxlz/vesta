import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import type { LoadingSpinnerProps } from "@/components/loading-spinner.types";
import { usePreferences } from "@/preferences/PreferencesProvider";

const SPINNER_SIZES = { small: 20, large: 36 } as const;
const SEGMENT_COUNT = 8;
const ROTATION_MS = 900;
const MIN_SEGMENT_OPACITY = 0.25;

// Hand-drawn segmented spinner: Android's native indeterminate drawable
// freezes into an arrow glyph when animations are off, so the segments
// keep the loading look in every state and match the iOS spinner.
export function LoadingSpinner({
  size = "small",
  color,
  style,
}: LoadingSpinnerProps) {
  const { colors } = usePreferences();
  const side = SPINNER_SIZES[size];
  const segmentColor = color ?? colors.secondaryText;
  const rotation = useSharedValue(0);
  useEffect(() => {
    rotation.value = withRepeat(
      withTiming(360, { duration: ROTATION_MS, easing: Easing.linear }),
      -1,
    );
  }, [rotation]);
  const spin = useAnimatedStyle(() => ({
    transform: [{ rotate: `${String(rotation.value)}deg` }],
  }));

  return (
    <Animated.View
      accessibilityRole="progressbar"
      style={[{ width: side, height: side }, spin, style]}
    >
      {Array.from({ length: SEGMENT_COUNT }, (_, index) => (
        <View
          key={index}
          style={[
            styles.segmentArm,
            { transform: [{ rotate: `${String((index * 360) / SEGMENT_COUNT)}deg` }] },
          ]}
        >
          <View
            style={{
              width: side * 0.11,
              height: side * 0.3,
              borderRadius: side * 0.06,
              backgroundColor: segmentColor,
              opacity:
                MIN_SEGMENT_OPACITY +
                (1 - MIN_SEGMENT_OPACITY) * (index / (SEGMENT_COUNT - 1)),
            }}
          />
        </View>
      ))}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  segmentArm: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "center",
  },
});

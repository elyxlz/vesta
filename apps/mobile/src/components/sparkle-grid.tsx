import { useEffect } from "react";
import { StyleSheet, useWindowDimensions, View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
  type SharedValue,
} from "react-native-reanimated";
import Svg, { Defs, Path, Pattern, Rect } from "react-native-svg";
import { usePreferences } from "@/preferences/PreferencesProvider";

// One tile holds a large sparkle and, half a tile down and across, a small
// one, so the rows stagger.
const TILE = 36;
const LARGE_RADIUS = 3;
const SMALL_RADIUS = 1.75;
// Pure grey with no warm tint, unlike the text color.
const NEUTRAL_DARK = "#000000";
const NEUTRAL_LIGHT = "#ffffff";
const LIGHT_OPACITY = 0.06;
const DARK_OPACITY = 0.035;
// The ripple: a ring of brighter sparkles that grows out from the orb.
const LIGHT_RIPPLE_OPACITY = 0.08;
const DARK_RIPPLE_OPACITY = 0.035;
const RIPPLE_PERIOD_MS = 4200;
const RIPPLE_RING_WIDTH = 90;
// The orb sits above the page center by half the wordmark and the gap.
const ORB_CENTER_OFFSET_Y = 31;

// A four-point star: four concave curves that meet at the center.
function sparkle(cx: number, cy: number, r: number): string {
  return [
    `M${String(cx)} ${String(cy - r)}`,
    `Q${String(cx)} ${String(cy)} ${String(cx + r)} ${String(cy)}`,
    `Q${String(cx)} ${String(cy)} ${String(cx)} ${String(cy + r)}`,
    `Q${String(cx)} ${String(cy)} ${String(cx - r)} ${String(cy)}`,
    `Q${String(cx)} ${String(cy)} ${String(cx)} ${String(cy - r)}Z`,
  ].join("");
}

const SPARKLES =
  sparkle(TILE / 4, TILE / 4, LARGE_RADIUS) +
  sparkle((TILE * 3) / 4, (TILE * 3) / 4, SMALL_RADIUS);

interface FieldProps {
  width: number;
  height: number;
  color: string;
  opacity: number;
}

// One page-sized, staggered grid of small sparkles.
function SparkleField({ width, height, color, opacity }: FieldProps) {
  // Shift the tiles so the left and right margins match.
  const offsetX = (width % (TILE / 2)) / 2;
  return (
    <Svg width={width} height={height} opacity={opacity}>
      <Defs>
        <Pattern
          id="sparkles"
          x={offsetX}
          y={0}
          width={TILE}
          height={TILE}
          patternUnits="userSpaceOnUse"
        >
          <Path d={SPARKLES} fill={color} />
        </Pattern>
      </Defs>
      <Rect width={width} height={height} fill="url(#sparkles)" />
    </Svg>
  );
}

// A disk that grows from the orb and shows the page-aligned children inside
// it. `lag` holds its edge that far behind the ripple front.
function RippleDisk({
  progress,
  lag,
  fades,
  backgroundColor,
  field,
}: {
  progress: SharedValue<number>;
  lag: number;
  fades: boolean;
  backgroundColor?: string;
  field: FieldProps;
}) {
  const centerX = field.width / 2;
  const centerY = field.height / 2 - ORB_CENTER_OFFSET_Y;
  const reach = Math.hypot(centerX, field.height - centerY) + lag;
  const diskStyle = useAnimatedStyle(() => {
    const radius = Math.max(0, progress.value * reach - lag);
    return {
      left: centerX - radius,
      top: centerY - radius,
      width: radius * 2,
      height: radius * 2,
      borderRadius: radius,
      opacity: fades
        ? Math.min(1, progress.value * 8) * (1 - progress.value)
        : 1,
    };
  });
  const fieldStyle = useAnimatedStyle(() => {
    const radius = Math.max(0, progress.value * reach - lag);
    return { left: radius - centerX, top: radius - centerY };
  });
  return (
    <Animated.View style={[styles.disk, { backgroundColor }, diskStyle]}>
      <Animated.View style={[styles.field, fieldStyle]}>
        <SparkleField {...field} />
      </Animated.View>
    </Animated.View>
  );
}

// A page-filling grid of sparkles in the text color, with a slow ripple of
// brighter sparkles that grows out from the orb.
export function SparkleGrid() {
  const { colors, dark } = usePreferences();
  const { width, height } = useWindowDimensions();
  const reduceMotion = useReducedMotion();
  const progress = useSharedValue(0);
  useEffect(() => {
    if (reduceMotion) return;
    progress.value = withRepeat(
      withTiming(1, {
        duration: RIPPLE_PERIOD_MS,
        easing: Easing.out(Easing.quad),
      }),
      -1,
      false,
    );
  }, [progress, reduceMotion]);
  const rest = dark ? DARK_OPACITY : LIGHT_OPACITY;
  const size = { width, height, color: dark ? NEUTRAL_LIGHT : NEUTRAL_DARK };
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <SparkleField {...size} opacity={rest} />
      {reduceMotion ? null : (
        <>
          <RippleDisk
            progress={progress}
            lag={0}
            fades
            field={{
              ...size,
              opacity: dark ? DARK_RIPPLE_OPACITY : LIGHT_RIPPLE_OPACITY,
            }}
          />
          <RippleDisk
            progress={progress}
            lag={RIPPLE_RING_WIDTH}
            fades={false}
            backgroundColor={colors.background}
            field={{ ...size, opacity: rest }}
          />
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  disk: { position: "absolute", overflow: "hidden" },
  field: { position: "absolute" },
});

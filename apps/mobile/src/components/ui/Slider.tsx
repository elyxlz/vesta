import {
  StyleSheet,
  View,
  type AccessibilityActionEvent,
  type LayoutChangeEvent,
} from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import { useSharedValue } from "react-native-reanimated";
import { scheduleOnRN } from "react-native-worklets";
import { usePreferences } from "@/preferences/PreferencesProvider";
import {
  positionToValue,
  stepValue,
  valueToFraction,
  type SliderRange,
} from "@/components/ui/slider-math";

const THUMB_SIZE = 24;
const RAIL_HEIGHT = 4;
const TOUCH_HEIGHT = 40;
// A sideways drag must clear this before the pan claims the touch; vertical travel past the
// fail offset first hands it to the page's scroll instead.
const ACTIVE_OFFSET_X = 8;
const FAIL_OFFSET_Y = 10;

interface SliderProps extends SliderRange {
  value: number;
  // Each stepped value under the finger while it moves; the owner shows it as `value`.
  onChange: (value: number) => void;
  // The value when the user lets go, or after one accessibility step.
  onCommit: (value: number) => void;
  disabled?: boolean;
  accessibilityLabel: string;
  // The value as the screen shows it, which a screen reader says in place of the number.
  valueText: string;
}

export function Slider({
  value,
  min,
  max,
  step,
  onChange,
  onCommit,
  disabled = false,
  accessibilityLabel,
  valueText,
}: SliderProps) {
  const { colors } = usePreferences();
  const range: SliderRange = { min, max, step };
  // The distance the middle of the thumb can travel, which is the width minus one thumb.
  const railLength = useSharedValue(0);
  const dragged = useSharedValue<number | null>(null);

  // The drag reports each new stepped value under the finger, and saves the last one on release.
  const pan = Gesture.Pan()
    .enabled(!disabled)
    .activeOffsetX([-ACTIVE_OFFSET_X, ACTIVE_OFFSET_X])
    .failOffsetY([-FAIL_OFFSET_Y, FAIL_OFFSET_Y])
    .onBegin(() => {
      dragged.set(null);
    })
    .onUpdate((event) => {
      const next = positionToValue(
        event.x - THUMB_SIZE / 2,
        railLength.get(),
        range,
      );
      if (next === dragged.get()) return;
      dragged.set(next);
      scheduleOnRN(onChange, next);
    })
    .onEnd(() => {
      const last = dragged.get();
      if (last !== null) scheduleOnRN(onCommit, last);
    });

  // A tap moves the thumb to the touch and saves at once.
  const tap = Gesture.Tap()
    .enabled(!disabled)
    .onEnd((event, success) => {
      if (!success) return;
      const next = positionToValue(
        event.x - THUMB_SIZE / 2,
        railLength.get(),
        range,
      );
      scheduleOnRN(onChange, next);
      scheduleOnRN(onCommit, next);
    });

  const measure = (event: LayoutChangeEvent) => {
    railLength.set(event.nativeEvent.layout.width - THUMB_SIZE);
  };

  const stepOnce = (event: AccessibilityActionEvent) => {
    const action = event.nativeEvent.actionName;
    if (action !== "increment" && action !== "decrement") return;
    const next = stepValue(value, action === "increment" ? 1 : -1, range);
    onChange(next);
    onCommit(next);
  };

  const filled = `${valueToFraction(value, range) * 100}%` as const;

  return (
    <GestureDetector gesture={Gesture.Race(pan, tap)}>
      <View
        accessible
        accessibilityRole="adjustable"
        accessibilityLabel={accessibilityLabel}
        accessibilityValue={{ text: valueText }}
        accessibilityState={{ disabled }}
        accessibilityActions={[{ name: "increment" }, { name: "decrement" }]}
        onAccessibilityAction={disabled ? undefined : stepOnce}
        collapsable={false}
        onLayout={measure}
        style={[styles.touch, disabled ? styles.disabled : null]}
      >
        <View style={[styles.rail, { backgroundColor: colors.input }]}>
          <View
            style={[
              styles.fill,
              { width: filled, backgroundColor: colors.accent },
            ]}
          />
          <View
            style={[styles.thumb, { left: filled, borderColor: colors.border }]}
          />
        </View>
      </View>
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  touch: {
    height: TOUCH_HEIGHT,
    justifyContent: "center",
    paddingHorizontal: THUMB_SIZE / 2,
  },
  disabled: { opacity: 0.5 },
  rail: { height: RAIL_HEIGHT, borderRadius: RAIL_HEIGHT / 2 },
  fill: { height: RAIL_HEIGHT, borderRadius: RAIL_HEIGHT / 2 },
  // The white thumb of the switch, on the same accent track.
  thumb: {
    position: "absolute",
    top: (RAIL_HEIGHT - THUMB_SIZE) / 2,
    width: THUMB_SIZE,
    height: THUMB_SIZE,
    marginLeft: -THUMB_SIZE / 2,
    borderRadius: THUMB_SIZE / 2,
    borderWidth: StyleSheet.hairlineWidth,
    backgroundColor: "#ffffff",
    shadowColor: "#000000",
    shadowOpacity: 0.18,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
    elevation: 2,
  },
});

import type { ReactNode } from "react";
import { StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from "react-native-reanimated";
import { scheduleOnRN } from "react-native-worklets";
import * as Haptics from "expo-haptics";
import { Ionicons } from "@expo/vector-icons";
import { usePreferences } from "@/preferences/PreferencesProvider";
import {
  swipeReplyArmed,
  swipeReplyOffset,
  swipeReplyProgress,
} from "@/agent/chat/swipe-reply-gesture";

// A rightward drag must clear this before the pan claims the touch; any vertical travel past
// the fail offset first hands it to the transcript's scroll instead.
const ACTIVE_OFFSET_X = 12;
const FAIL_OFFSET_Y = 10;
const RETURN_SPRING = { dampingRatio: 1, duration: 300 };

function tickHaptic() {
  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(
    () => undefined,
  );
}

export function SwipeToReply({
  children,
  onReply,
  style,
}: {
  children: ReactNode;
  onReply: () => void;
  style?: StyleProp<ViewStyle>;
}) {
  const { colors } = usePreferences();
  const offset = useSharedValue(0);
  const armed = useSharedValue(false);

  const pan = Gesture.Pan()
    .activeOffsetX(ACTIVE_OFFSET_X)
    .failOffsetY([-FAIL_OFFSET_Y, FAIL_OFFSET_Y])
    .onUpdate((event) => {
      const next = swipeReplyOffset(event.translationX);
      offset.set(next);
      const nextArmed = swipeReplyArmed(next);
      if (nextArmed && !armed.get()) scheduleOnRN(tickHaptic);
      armed.set(nextArmed);
    })
    .onFinalize((event, success) => {
      if (success && armed.get()) scheduleOnRN(onReply);
      armed.set(false);
      offset.set(
        withSpring(0, { ...RETURN_SPRING, velocity: event.velocityX }),
      );
    });

  const rowStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: offset.get() }],
  }));
  const iconStyle = useAnimatedStyle(() => {
    const progress = swipeReplyProgress(offset.get());
    return {
      opacity: progress,
      transform: [{ scale: 0.5 + progress * 0.5 }],
    };
  });

  return (
    <View style={styles.frame}>
      <Animated.View
        pointerEvents="none"
        style={[styles.icon, { backgroundColor: colors.input }, iconStyle]}
      >
        <Ionicons name="arrow-undo" size={16} color={colors.secondaryText} />
      </Animated.View>
      <GestureDetector gesture={pan}>
        <Animated.View style={[style, rowStyle]}>{children}</Animated.View>
      </GestureDetector>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { width: "100%", justifyContent: "center" },
  icon: {
    position: "absolute",
    left: 16,
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: "center",
    justifyContent: "center",
  },
});

import { useEffect, useRef, useState } from "react";
import { Animated, Easing, StyleSheet, View } from "react-native";
import * as Haptics from "expo-haptics";
import { LinearGradient } from "expo-linear-gradient";
import type { AgentActivityState, AgentStatus } from "@vesta/core";
import { useBootTransitionTargetFrozen } from "@/components/BootTransition";
import { designTokens } from "@/theme/generated";

interface AgentOrbProps {
  status: AgentStatus;
  activityState?: AgentActivityState;
  size?: number;
  animated?: boolean;
  pulseScale?: number;
  pulseDuration?: number;
  pulseHaptics?: boolean;
}

function orbColors(
  status: AgentStatus,
  activityState: AgentActivityState,
): readonly [string, string, string] {
  if (status === "alive") {
    return activityState === "thinking"
      ? designTokens.orb.thinking
      : designTokens.orb.alive;
  }
  if (
    status === "starting" ||
    status === "restarting" ||
    status === "rebuilding"
  ) {
    return designTokens.orb.busy;
  }
  if (
    status === "setting_up" ||
    status === "not_authenticated" ||
    status === "unprovisioned"
  ) {
    return designTokens.orb.busy;
  }
  return designTokens.orb.off;
}

export function AgentOrb({
  status,
  activityState = "idle",
  size = 88,
  animated = true,
  pulseScale,
  pulseDuration,
  pulseHaptics = false,
}: AgentOrbProps) {
  const [rotation] = useState(() => new Animated.Value(0));
  const [pulse] = useState(() => new Animated.Value(1));
  const pulseHapticsEnabled = useRef(pulseHaptics);
  const transitionFrozen = useBootTransitionTargetFrozen();
  const shouldAnimate = animated && !transitionFrozen;
  const colors = orbColors(status, activityState);
  const maximumPulseScale =
    pulseScale ?? (activityState === "thinking" ? 1.1 : 1.04);
  const halfPulseDuration =
    pulseDuration ?? (activityState === "thinking" ? 1200 : 1800);

  useEffect(() => {
    pulseHapticsEnabled.current = pulseHaptics;
  }, [pulseHaptics]);

  useEffect(() => {
    if (!shouldAnimate) {
      rotation.setValue(0);
      return;
    }

    const rotate = Animated.loop(
      Animated.timing(rotation, {
        toValue: 1,
        duration: activityState === "thinking" ? 2600 : 9000,
        easing: Easing.linear,
        useNativeDriver: true,
      }),
    );
    rotate.start();
    return () => rotate.stop();
  }, [activityState, rotation, shouldAnimate]);

  useEffect(() => {
    if (!shouldAnimate || status !== "alive") {
      pulse.stopAnimation();
      pulse.setValue(1);
      return;
    }

    let active = true;
    let currentAnimation: Animated.CompositeAnimation | undefined;

    const runCycle = () => {
      currentAnimation = Animated.timing(pulse, {
        toValue: maximumPulseScale,
        duration: halfPulseDuration,
        easing: Easing.inOut(Easing.sin),
        useNativeDriver: true,
      });
      currentAnimation.start(({ finished: reachedPeak }) => {
        if (!active || !reachedPeak) {
          return;
        }

        if (
          pulseHapticsEnabled.current &&
          process.env.EXPO_OS === "ios"
        ) {
          void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Soft).catch(
            () => undefined,
          );
        }

        currentAnimation = Animated.timing(pulse, {
          toValue: 1,
          duration: halfPulseDuration,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true,
        });
        currentAnimation.start(({ finished: reachedRest }) => {
          if (active && reachedRest) {
            runCycle();
          }
        });
      });
    };

    runCycle();

    return () => {
      active = false;
      currentAnimation?.stop();
    };
  }, [halfPulseDuration, maximumPulseScale, pulse, shouldAnimate, status]);

  const rotate = rotation.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "360deg"],
  });

  return (
    <Animated.View
      style={[
        styles.shell,
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          shadowColor: colors[1],
        },
        { transform: [{ scale: pulse }] },
      ]}
    >
      <Animated.View
        style={[StyleSheet.absoluteFill, { transform: [{ rotate }] }]}
      >
        <LinearGradient
          colors={colors}
          start={{ x: 0.15, y: 0 }}
          end={{ x: 0.9, y: 1 }}
          style={{ flex: 1, borderRadius: size / 2 }}
        />
      </Animated.View>
      <View
        style={[
          styles.highlight,
          {
            width: size * 0.42,
            height: size * 0.24,
            borderRadius: size,
            top: size * 0.16,
            left: size * 0.18,
          },
        ]}
      />
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  shell: {
    overflow: "hidden",
    shadowOpacity: 0.42,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
    elevation: 9,
  },
  highlight: {
    position: "absolute",
    backgroundColor: "rgba(255,255,255,0.34)",
    transform: [{ rotate: "-24deg" }],
  },
});

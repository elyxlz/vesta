import { use, useEffect, useRef, useState } from "react";
import { Animated, Easing, StyleSheet, View } from "react-native";
import * as Haptics from "expo-haptics";
import { LinearGradient } from "expo-linear-gradient";
import {
  agentVisualStatus,
  orbVisual,
  type AgentActivityState,
  type AgentOperation,
  type AgentStatus,
  type RateLimitedInfo,
} from "@vesta/core";
import { useAgentRequest } from "@vesta/core/react";
import { useBootTransitionTargetFrozen } from "@/components/BootTransition";
import { ControllerContext } from "@/controller/context";
import { designTokens } from "@/theme/generated";

interface AgentOrbProps {
  // The roster agent, so this client's own in-flight request overlays the orb; a nameless orb
  // (the brand mark, the boot splash) renders the status alone.
  name?: string;
  status: AgentStatus;
  activityState?: AgentActivityState;
  operation?: AgentOperation | null;
  booting?: boolean;
  rateLimited?: RateLimitedInfo | null;
  size?: number;
  animated?: boolean;
  pulseScale?: number;
  pulseDuration?: number;
  pulseHaptics?: boolean;
}

export function AgentOrb({
  name,
  status,
  activityState = "idle",
  operation = null,
  booting = false,
  rateLimited = null,
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
  const { request } = useAgentRequest(use(ControllerContext), name ?? null);
  const { orbState } = agentVisualStatus(
    { status, operation, booting, rateLimited },
    request,
    activityState,
  );
  const visual = orbVisual(orbState);
  const shouldAnimate = animated && !transitionFrozen && visual.live;
  const colors = designTokens.orb[orbState];
  // Breathing is what "the agent itself is up" looks like, so it follows the resolved orb state:
  // a restore on a still-alive agent reads busy and must not keep breathing.
  const breathes = visual.breathes;
  const maximumPulseScale = pulseScale ?? visual.pulseScale;
  const halfPulseDuration = pulseDuration ?? visual.pulseHalfMs;
  const highlight = visual.highlight;

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
        duration: visual.rotationMs,
        easing: Easing.linear,
        useNativeDriver: true,
      }),
    );
    rotate.start();
    return () => rotate.stop();
  }, [rotation, shouldAnimate, visual.rotationMs]);

  useEffect(() => {
    if (!shouldAnimate || !breathes) {
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

        if (pulseHapticsEnabled.current && process.env.EXPO_OS === "ios") {
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
  }, [breathes, halfPulseDuration, maximumPulseScale, pulse, shouldAnimate]);

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
          start={visual.gradient.start}
          end={visual.gradient.end}
          style={{ flex: 1, borderRadius: size / 2 }}
        />
      </Animated.View>
      <View
        style={[
          styles.highlight,
          {
            width: size * highlight.wRatio,
            height: size * highlight.hRatio,
            borderRadius: size,
            top: size * (highlight.cy - highlight.hRatio / 2),
            left: size * (highlight.cx - highlight.wRatio / 2),
            backgroundColor: `rgba(255,255,255,${String(highlight.alpha)})`,
            transform: [{ rotate: `${String(highlight.angleDeg)}deg` }],
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
  },
});

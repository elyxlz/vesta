import { useCallback, useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  AppState,
  StyleSheet,
  View,
  useWindowDimensions,
} from "react-native";
import * as SplashScreen from "expo-splash-screen";
import Animated, {
  cancelAnimation,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import { scheduleOnRN } from "react-native-worklets";
import { AgentOrb } from "@/components/AgentOrb";
import type { BootTargetFrame } from "@/components/BootTransition";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { designTokens } from "@/theme/generated";

const ORB_SIZE = 176;
const INITIAL_SCALE = 24 / ORB_SIZE;
const HOLDING_ORB_SIZE = 64 * 1.1;
const HOLDING_SCALE = HOLDING_ORB_SIZE / ORB_SIZE;
const DISCONNECT_DELAY_MS = 10_000;
const HANDOFF_DURATION_MS = 140;
const TRAVEL_ENERGY_THRESHOLD = 1e-4;

export function BootSplash({
  ready,
  target,
  targetExpected,
  onDisconnect,
  onHandoff,
  onReveal,
  onFinish,
}: {
  ready: boolean;
  target: BootTargetFrame | null;
  targetExpected: boolean;
  onDisconnect?: () => Promise<void>;
  onHandoff: () => void;
  onReveal: () => void;
  onFinish: () => void;
}) {
  const { width: windowWidth, height: windowHeight } = useWindowDimensions();
  const { colors } = usePreferences();
  const scale = useSharedValue(INITIAL_SCALE);
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);
  const backdropOpacity = useSharedValue(1);
  const orbOpacity = useSharedValue(1);
  const delayMessageOpacity = useSharedValue(0);
  const disconnectButtonOpacity = useSharedValue(0);
  const entranceStarted = useRef(false);
  const travelStarted = useRef(false);
  const handoffStarted = useRef(false);
  const completed = useRef(false);
  const travelWatchdog = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handoffFrame = useRef<number | null>(null);
  const [holding, setHolding] = useState(false);
  const [handingOff, setHandingOff] = useState(false);
  const [nativeSplashHidden, setNativeSplashHidden] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [appActive, setAppActive] = useState(
    () => AppState.currentState === "active",
  );
  const [disconnectVisible, setDisconnectVisible] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const showDisconnect =
    disconnectVisible && !ready && onDisconnect !== undefined;
  const complete = useCallback(() => {
    if (completed.current) return;
    completed.current = true;
    onFinish();
  }, [onFinish]);
  const startHandoff = useCallback(() => {
    if (handoffStarted.current) return;
    handoffStarted.current = true;
    if (travelWatchdog.current) {
      clearTimeout(travelWatchdog.current);
      travelWatchdog.current = null;
    }
    setHandingOff(true);
    onHandoff();
    if (reduceMotion) {
      complete();
      return;
    }
    handoffFrame.current = requestAnimationFrame(() => {
      handoffFrame.current = null;
      orbOpacity.set(
        withTiming(0, { duration: HANDOFF_DURATION_MS }, (finished) => {
          if (finished) scheduleOnRN(complete);
        }),
      );
    });
  }, [complete, onHandoff, orbOpacity, reduceMotion]);
  const markHolding = useCallback(() => setHolding(true), []);
  const backdropStyle = useAnimatedStyle(() => ({
    opacity: backdropOpacity.value,
  }));
  const orbStyle = useAnimatedStyle(() => ({
    opacity: orbOpacity.value,
    transform: [
      { translateX: translateX.value },
      { translateY: translateY.value },
      { scale: scale.value },
    ],
  }));
  const delayMessageStyle = useAnimatedStyle(() => ({
    opacity: delayMessageOpacity.value,
  }));
  const disconnectButtonStyle = useAnimatedStyle(() => ({
    opacity: disconnectButtonOpacity.value,
  }));

  useEffect(() => {
    let active = true;

    void AccessibilityInfo.isReduceMotionEnabled()
      .catch(() => false)
      .then(async (reduced) => {
        if (!active) return;
        setReduceMotion(reduced);
        await SplashScreen.hideAsync().catch(() => undefined);
        if (active) setNativeSplashHidden(true);
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      setAppActive(state === "active");
    });
    return () => subscription.remove();
  }, []);

  useEffect(
    () => () => {
      if (travelWatchdog.current) clearTimeout(travelWatchdog.current);
      if (handoffFrame.current !== null) {
        cancelAnimationFrame(handoffFrame.current);
      }
      cancelAnimation(backdropOpacity);
      cancelAnimation(orbOpacity);
      cancelAnimation(scale);
      cancelAnimation(translateX);
      cancelAnimation(translateY);
    },
    [backdropOpacity, orbOpacity, scale, translateX, translateY],
  );

  useEffect(() => {
    if (ready || !onDisconnect || !appActive) return;
    const timeout = setTimeout(
      () => setDisconnectVisible(true),
      DISCONNECT_DELAY_MS,
    );
    return () => clearTimeout(timeout);
  }, [appActive, onDisconnect, ready]);

  useEffect(() => {
    cancelAnimation(delayMessageOpacity);
    cancelAnimation(disconnectButtonOpacity);

    if (!showDisconnect) {
      delayMessageOpacity.set(0);
      disconnectButtonOpacity.set(0);
      return;
    }

    if (reduceMotion) {
      delayMessageOpacity.set(1);
      disconnectButtonOpacity.set(1);
      return;
    }

    delayMessageOpacity.set(withTiming(1, { duration: 360 }));
    disconnectButtonOpacity.set(
      withDelay(1000, withTiming(1, { duration: 360 })),
    );
    return () => {
      cancelAnimation(delayMessageOpacity);
      cancelAnimation(disconnectButtonOpacity);
    };
  }, [
    delayMessageOpacity,
    disconnectButtonOpacity,
    reduceMotion,
    showDisconnect,
  ]);

  useEffect(() => {
    if (!nativeSplashHidden || entranceStarted.current) return;
    entranceStarted.current = true;

    if (reduceMotion) {
      scale.set(HOLDING_SCALE);
      const frame = requestAnimationFrame(markHolding);
      return () => cancelAnimationFrame(frame);
    }

    scale.set(
      withSpring(
        HOLDING_SCALE,
        {
          stiffness: 180,
          damping: 18,
          mass: 0.7,
        },
        (finished) => {
          if (finished) scheduleOnRN(markHolding);
        },
      ),
    );
    return () => cancelAnimation(scale);
  }, [markHolding, nativeSplashHidden, reduceMotion, scale]);

  useEffect(() => {
    if (
      !nativeSplashHidden ||
      !holding ||
      !ready ||
      travelStarted.current ||
      (targetExpected && !target)
    ) {
      return;
    }

    let secondFrame: number | null = null;
    const firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => {
        if (travelStarted.current) return;
        travelStarted.current = true;

        if (reduceMotion || !target) {
          onReveal();
          startHandoff();
          return;
        }

        const destinationX = target.x + target.width / 2 - windowWidth / 2;
        const destinationY = target.y + target.height / 2 - windowHeight / 2;
        const spring = {
          stiffness: 150,
          damping: 17,
          mass: 0.82,
          energyThreshold: TRAVEL_ENERGY_THRESHOLD,
        } as const;
        travelWatchdog.current = setTimeout(startHandoff, 3500);
        onReveal();
        backdropOpacity.set(withTiming(0, { duration: 280 }));
        scale.set(withSpring(target.width / ORB_SIZE, spring));
        translateX.set(withSpring(destinationX, spring));
        translateY.set(
          withSpring(destinationY, spring, (finished) => {
            if (finished) scheduleOnRN(startHandoff);
          }),
        );
      });
    });

    return () => {
      cancelAnimationFrame(firstFrame);
      if (secondFrame !== null) cancelAnimationFrame(secondFrame);
    };
  }, [
    nativeSplashHidden,
    backdropOpacity,
    holding,
    ready,
    reduceMotion,
    onReveal,
    scale,
    startHandoff,
    target,
    targetExpected,
    translateX,
    translateY,
    windowHeight,
    windowWidth,
  ]);

  return (
    <View
      accessibilityElementsHidden={!showDisconnect}
      importantForAccessibility={
        showDisconnect ? "auto" : "no-hide-descendants"
      }
      pointerEvents={handingOff ? "none" : "auto"}
      style={styles.screen}
    >
      <Animated.View
        style={[
          styles.backdrop,
          { backgroundColor: colors.background },
          backdropStyle,
        ]}
      />
      <Animated.View style={orbStyle}>
        <AgentOrb
          status={target?.status ?? "alive"}
          activityState={target?.activityState}
          size={ORB_SIZE}
          animated={!reduceMotion && holding && !ready}
          pulseScale={1.1}
          pulseDuration={2000}
        />
      </Animated.View>
      {showDisconnect && onDisconnect ? (
        <>
          <Animated.View
            style={[styles.gatewayDelayMessage, delayMessageStyle]}
          >
            <Text
              style={[
                styles.gatewayDelayMessageText,
                { color: colors.text },
              ]}
            >
              Reaching the gateway is taking longer than expected
            </Text>
          </Animated.View>
          <Animated.View style={[styles.disconnect, disconnectButtonStyle]}>
            <Button
              pill
              size="small"
              variant="secondary"
              icon="log-out-outline"
              iconColor={colors.danger}
              loading={disconnecting}
              onPress={() => {
                if (disconnecting) return;
                setDisconnecting(true);
                void onDisconnect().catch(() => setDisconnecting(false));
              }}
            >
              Disconnect gateway
            </Button>
          </Animated.View>
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    zIndex: 1000,
    elevation: 1000,
    alignItems: "center",
    justifyContent: "center",
  },
  backdrop: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
  },
  disconnect: {
    position: "absolute",
    left: 24,
    right: 24,
    bottom: 42,
    alignItems: "center",
  },
  gatewayDelayMessage: {
    position: "absolute",
    top: "50%",
    left: 24,
    right: 24,
    marginTop: HOLDING_ORB_SIZE / 2 + 20,
  },
  gatewayDelayMessageText: {
    fontSize: designTokens.typography.sizes.base,
    lineHeight: 22,
    textAlign: "center",
  },
});

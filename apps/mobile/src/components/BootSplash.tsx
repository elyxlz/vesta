import { useCallback, useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  Animated,
  StyleSheet,
  View,
  useWindowDimensions,
} from "react-native";
import * as SplashScreen from "expo-splash-screen";
import { AgentOrb } from "@/components/AgentOrb";
import type { BootTargetFrame } from "@/components/BootTransition";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { ThemeOverrideProvider } from "@/preferences/PreferencesProvider";
import { designTokens } from "@/theme/generated";

const ORB_SIZE = 176;
const INITIAL_SCALE = 24 / ORB_SIZE;
const HOLDING_ORB_SIZE = 64 * 1.1;
const HOLDING_SCALE = HOLDING_ORB_SIZE / ORB_SIZE;
const DISCONNECT_DELAY_MS = 10_000;

export function BootSplash({
  ready,
  target,
  targetExpected,
  onDisconnect,
  onReveal,
  onFinish,
}: {
  ready: boolean;
  target: BootTargetFrame | null;
  targetExpected: boolean;
  onDisconnect?: () => Promise<void>;
  onReveal: () => void;
  onFinish: () => void;
}) {
  const { width: windowWidth, height: windowHeight } = useWindowDimensions();
  const [scale] = useState(() => new Animated.Value(INITIAL_SCALE));
  const [translateX] = useState(() => new Animated.Value(0));
  const [translateY] = useState(() => new Animated.Value(0));
  const [backdropOpacity] = useState(() => new Animated.Value(1));
  const [delayMessageOpacity] = useState(() => new Animated.Value(0));
  const [disconnectButtonOpacity] = useState(() => new Animated.Value(0));
  const entranceStarted = useRef(false);
  const travelStarted = useRef(false);
  const completed = useRef(false);
  const [holding, setHolding] = useState(false);
  const [nativeSplashHidden, setNativeSplashHidden] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [disconnectVisible, setDisconnectVisible] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const showDisconnect =
    disconnectVisible && !ready && onDisconnect !== undefined;
  const complete = useCallback(() => {
    if (completed.current) return;
    completed.current = true;
    onFinish();
  }, [onFinish]);

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
    if (ready || !onDisconnect) return;
    const timeout = setTimeout(
      () => setDisconnectVisible(true),
      DISCONNECT_DELAY_MS,
    );
    return () => clearTimeout(timeout);
  }, [onDisconnect, ready]);

  useEffect(() => {
    if (!showDisconnect) {
      delayMessageOpacity.setValue(0);
      disconnectButtonOpacity.setValue(0);
      return;
    }

    if (reduceMotion) {
      delayMessageOpacity.setValue(1);
      disconnectButtonOpacity.setValue(1);
      return;
    }

    const reveal = Animated.stagger(1000, [
      Animated.timing(delayMessageOpacity, {
        toValue: 1,
        duration: 360,
        useNativeDriver: true,
      }),
      Animated.timing(disconnectButtonOpacity, {
        toValue: 1,
        duration: 360,
        useNativeDriver: true,
      }),
    ]);
    reveal.start();
    return () => reveal.stop();
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
      scale.setValue(HOLDING_SCALE);
      const frame = requestAnimationFrame(() => setHolding(true));
      return () => cancelAnimationFrame(frame);
    }

    const entrance = Animated.spring(scale, {
      toValue: HOLDING_SCALE,
      stiffness: 180,
      damping: 18,
      mass: 0.7,
      useNativeDriver: true,
    });
    entrance.start(({ finished }) => {
      if (finished) setHolding(true);
    });
  }, [nativeSplashHidden, reduceMotion, scale]);

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
          complete();
          return;
        }

        const destinationX = target.x + target.width / 2 - windowWidth / 2;
        const destinationY = target.y + target.height / 2 - windowHeight / 2;
        const spring = {
          stiffness: 150,
          damping: 17,
          mass: 0.82,
          useNativeDriver: true,
        } as const;
        const watchdog = setTimeout(complete, 3500);
        const transition = Animated.parallel([
          Animated.spring(backdropOpacity, {
            ...spring,
            toValue: 0,
            overshootClamping: true,
          }),
          Animated.spring(scale, {
            ...spring,
            toValue: target.width / ORB_SIZE,
          }),
          Animated.spring(translateX, {
            ...spring,
            toValue: destinationX,
          }),
          Animated.spring(translateY, {
            ...spring,
            toValue: destinationY,
          }),
        ]);
        onReveal();
        transition.start(({ finished }) => {
          clearTimeout(watchdog);
          if (finished) complete();
        });
      });
    });

    return () => {
      cancelAnimationFrame(firstFrame);
      if (secondFrame !== null) cancelAnimationFrame(secondFrame);
    };
  }, [
    nativeSplashHidden,
    backdropOpacity,
    complete,
    holding,
    ready,
    reduceMotion,
    onReveal,
    scale,
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
      style={styles.screen}
    >
      <Animated.View style={[styles.backdrop, { opacity: backdropOpacity }]} />
      <Animated.View
        style={{
          transform: [{ translateX }, { translateY }, { scale }],
        }}
      >
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
        <ThemeOverrideProvider theme="light">
          <>
            <Animated.View
              style={[
                styles.gatewayDelayMessage,
                { opacity: delayMessageOpacity },
              ]}
            >
              <Text style={styles.gatewayDelayMessageText}>
                Reaching the gateway is taking longer than expected
              </Text>
            </Animated.View>
            <Animated.View
              style={[
                styles.disconnect,
                { opacity: disconnectButtonOpacity },
              ]}
            >
              <Button
                pill
                size="small"
                variant="danger"
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
        </ThemeOverrideProvider>
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
    backgroundColor: designTokens.launch.background,
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
    color: designTokens.colors.light["muted-foreground"],
    fontSize: designTokens.typography.sizes.base,
    lineHeight: 22,
    textAlign: "center",
  },
});

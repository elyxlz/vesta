import { useEffect } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import Reanimated, {
  Easing,
  FadeInUp,
  FadeOutDown,
  cancelAnimation,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import { Text } from "@/components/ui/Typography";
import { GlassSurface } from "@/components/ui/glass-surface";
import { usePreferences } from "@/preferences/PreferencesProvider";

export type VoiceConversationState = "connecting" | "listening" | "speaking";

const PANEL_ENTER_MS = 260;
const PANEL_EXIT_MS = 180;
const ORB_PULSE_MS = 1100;
const ORB_SIZE = 14;
const CONTROL_HEIGHT = 56;

const STATE_LABELS: Record<VoiceConversationState, string> = {
  connecting: "Connecting…",
  listening: "Listening",
  speaking: "Speaking",
};

function StatusOrb({ state }: { state: VoiceConversationState }) {
  const { colors } = usePreferences();
  const reducedMotion = useReducedMotion();
  const pulse = useSharedValue(1);
  const live = state === "listening" || state === "speaking";

  useEffect(() => {
    if (!live || reducedMotion) {
      cancelAnimation(pulse);
      pulse.set(withTiming(1, { duration: 160 }));
      return;
    }
    pulse.set(
      withRepeat(
        withTiming(1.25, {
          duration: ORB_PULSE_MS,
          easing: Easing.inOut(Easing.ease),
        }),
        -1,
        true,
      ),
    );
    return () => {
      cancelAnimation(pulse);
    };
  }, [live, pulse, reducedMotion]);

  const pulseStyle = useAnimatedStyle(() => ({
    transform: [{ scale: pulse.value }],
  }));
  const orbColor =
    state === "speaking"
      ? colors.accent
      : state === "listening"
        ? colors.danger
        : colors.tertiaryText;

  return (
    <Reanimated.View
      style={[styles.orb, { backgroundColor: orbColor }, pulseStyle]}
    />
  );
}

// The hands-free surface docked over the composer: glanceable state, the live
// transcript, and two large targets, sized for use at arm's length in a car.
export function VoiceConversationPanel({
  state,
  transcript,
  height,
  onEnd,
}: {
  state: VoiceConversationState;
  transcript: string;
  height: number;
  onEnd: () => void;
}) {
  const { colors } = usePreferences();

  return (
    <Reanimated.View
      entering={FadeInUp.duration(PANEL_ENTER_MS).easing(
        Easing.bezier(0.32, 0.72, 0, 1).factory(),
      )}
      exiting={FadeOutDown.duration(PANEL_EXIT_MS)}
    >
      <GlassSurface style={[styles.panel, { height }]}>
        <View style={styles.statusRow}>
          <StatusOrb state={state} />
          <Text style={[styles.statusLabel, { color: colors.text }]}>
            {STATE_LABELS[state]}
          </Text>
        </View>
        <View style={styles.transcriptArea}>
          {transcript ? (
            <Text
              numberOfLines={4}
              style={[styles.transcript, { color: colors.text }]}
            >
              {transcript}
            </Text>
          ) : (
            <Text style={[styles.transcriptHint, { color: colors.tertiaryText }]}>
              Just start talking
            </Text>
          )}
        </View>
        <View style={styles.controlsRow}>
          <Pressable
            accessibilityLabel="End voice conversation"
            accessibilityRole="button"
            onPress={onEnd}
            style={({ pressed }) => [
              styles.endButton,
              {
                backgroundColor: colors.danger,
                opacity: pressed ? 0.72 : 1,
              },
            ]}
          >
            <Text style={styles.endLabel}>End</Text>
          </Pressable>
        </View>
      </GlassSurface>
    </Reanimated.View>
  );
}

const styles = StyleSheet.create({
  panel: {
    padding: 20,
    borderRadius: 28,
    overflow: "hidden",
  },
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  orb: {
    width: ORB_SIZE,
    height: ORB_SIZE,
    borderRadius: ORB_SIZE / 2,
  },
  statusLabel: {
    fontSize: 17,
    fontWeight: "600",
  },
  transcriptArea: {
    flex: 1,
    justifyContent: "center",
  },
  transcript: {
    fontSize: 20,
    lineHeight: 27,
  },
  transcriptHint: {
    fontSize: 17,
  },
  controlsRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  muteButton: {
    width: CONTROL_HEIGHT,
    height: CONTROL_HEIGHT,
    borderRadius: CONTROL_HEIGHT / 2,
    alignItems: "center",
    justifyContent: "center",
  },
  endButton: {
    flex: 1,
    height: CONTROL_HEIGHT,
    borderRadius: CONTROL_HEIGHT / 2,
    alignItems: "center",
    justifyContent: "center",
  },
  endLabel: {
    color: "white",
    fontSize: 17,
    fontWeight: "600",
  },
});

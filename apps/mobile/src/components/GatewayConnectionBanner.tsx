import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  GlassView,
  isGlassEffectAPIAvailable,
  type GlassViewProps,
} from "expo-glass-effect";
import Animated, {
  Easing,
  useAnimatedProps,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

const ANIMATION_DURATION_MS = 220;
const AnimatedGlassView = Animated.createAnimatedComponent(GlassView);

export function GatewayConnectionBanner({ visible }: { visible: boolean }) {
  const insets = useSafeAreaInsets();
  const { colors, dark } = usePreferences();
  const progress = useSharedValue(visible ? 1 : 0);

  useEffect(() => {
    progress.value = withTiming(visible ? 1 : 0, {
      duration: ANIMATION_DURATION_MS,
      easing: visible ? Easing.out(Easing.cubic) : Easing.in(Easing.cubic),
    });
  }, [progress, visible]);

  const overlayStyle = useAnimatedStyle(() => ({
    opacity: progress.value,
    transform: [{ translateY: -8 * (1 - progress.value) }],
  }));
  const glassAnimatedProps = useAnimatedProps<GlassViewProps>(() => ({
    glassEffectStyle: progress.value > 0.01 ? "regular" : "none",
  }));

  const content = (
    <>
      <View style={[styles.icon, { backgroundColor: colors.input }]}>
        <Ionicons
          name="cloud-offline-outline"
          size={19}
          color={colors.danger}
        />
      </View>
      <View style={styles.copy}>
        <Text style={[styles.title, { color: colors.text }]}>
          Gateway disconnected
        </Text>
      </View>
      <ActivityIndicator size="small" color={colors.text} />
    </>
  );

  return (
    <Animated.View
      accessibilityElementsHidden={!visible}
      accessibilityLiveRegion="polite"
      accessibilityRole="alert"
      accessibilityLabel="Gateway disconnected. Trying to reconnect."
      pointerEvents="none"
      style={[
        styles.overlay,
        {
          top: insets.top + 52,
        },
        overlayStyle,
      ]}
    >
      {isGlassEffectAPIAvailable() ? (
        <AnimatedGlassView
          animatedProps={glassAnimatedProps}
          colorScheme={dark ? "dark" : "light"}
          style={[styles.banner, { shadowColor: colors.text }]}
        >
          {content}
        </AnimatedGlassView>
      ) : (
        <View
          style={[
            styles.banner,
            styles.fallback,
            {
              backgroundColor: colors.elevated,
              borderColor: colors.border,
              shadowColor: colors.text,
            },
          ]}
        >
          {content}
        </View>
      )}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    position: "absolute",
    zIndex: 100,
    left: 16,
    right: 16,
    alignItems: "center",
  },
  banner: {
    width: "100%",
    maxWidth: 420,
    minHeight: 54,
    borderRadius: radii.pill,
    paddingHorizontal: 12,
    paddingVertical: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    shadowOpacity: 0.12,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 5 },
    elevation: 8,
    overflow: "hidden",
  },
  fallback: { borderWidth: StyleSheet.hairlineWidth },
  icon: {
    width: 34,
    height: 34,
    borderRadius: 11,
    alignItems: "center",
    justifyContent: "center",
  },
  copy: { flex: 1 },
  title: { fontSize: 14, fontWeight: "600" },
});

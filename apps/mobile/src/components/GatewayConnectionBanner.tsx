import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  Easing,
  StyleSheet,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

const ANIMATION_DURATION_MS = 220;

export function GatewayConnectionBanner({ visible }: { visible: boolean }) {
  const insets = useSafeAreaInsets();
  const { colors } = usePreferences();
  const [progress] = useState(() => new Animated.Value(visible ? 1 : 0));

  useEffect(() => {
    Animated.timing(progress, {
      toValue: visible ? 1 : 0,
      duration: ANIMATION_DURATION_MS,
      easing: visible ? Easing.out(Easing.cubic) : Easing.in(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [progress, visible]);

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
          opacity: progress,
          transform: [
            {
              translateY: progress.interpolate({
                inputRange: [0, 1],
                outputRange: [-8, 0],
              }),
            },
          ],
        },
      ]}
    >
      <View
        style={[
          styles.banner,
          {
            backgroundColor: colors.elevated,
            borderColor: colors.warning,
            shadowColor: colors.text,
          },
        ]}
      >
        <View style={[styles.icon, { backgroundColor: colors.input }]}>
          <Ionicons
            name="cloud-offline-outline"
            size={19}
            color={colors.warning}
          />
        </View>
        <View style={styles.copy}>
          <Text style={[styles.title, { color: colors.text }]}>
            Gateway disconnected
          </Text>
          <Text style={[styles.detail, { color: colors.secondaryText }]}>
            Trying to reconnect
          </Text>
        </View>
        <ActivityIndicator size="small" color={colors.warning} />
      </View>
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
    borderRadius: radii.control,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 12,
    paddingVertical: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    shadowOpacity: 0.12,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 5 },
    elevation: 8,
  },
  icon: {
    width: 34,
    height: 34,
    borderRadius: 11,
    alignItems: "center",
    justifyContent: "center",
  },
  copy: { flex: 1, gap: 1 },
  title: { fontSize: 14, fontWeight: "600" },
  detail: { fontSize: 12 },
});

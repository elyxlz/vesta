import type { ReactNode } from "react";
import { StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import { GlassView, isGlassEffectAPIAvailable } from "expo-glass-effect";
import { usePreferences } from "@/preferences/PreferencesProvider";

export const GLASS_TRANSITION_MS = 180;

// `materialized={false}` dissolves the glass with UIKit's own transition,
// the one way a glass view can appear or vanish: it ignores ancestor opacity.
export function GlassSurface({
  children,
  style,
  materialized = true,
}: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  materialized?: boolean;
}) {
  const { colors, dark } = usePreferences();
  if (isGlassEffectAPIAvailable()) {
    return (
      <GlassView
        glassEffectStyle={{
          style: materialized ? "regular" : "none",
          animate: true,
          animationDuration: GLASS_TRANSITION_MS / 1000,
        }}
        colorScheme={dark ? "dark" : "light"}
        isInteractive
        style={style}
      >
        {children}
      </GlassView>
    );
  }
  return (
    <View
      style={[
        style,
        {
          backgroundColor: colors.elevated,
          borderColor: colors.border,
          borderWidth: StyleSheet.hairlineWidth,
        },
      ]}
    >
      {children}
    </View>
  );
}

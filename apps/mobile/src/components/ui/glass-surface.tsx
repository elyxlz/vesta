import type { ReactNode } from "react";
import {
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import {
  GlassView,
  isGlassEffectAPIAvailable,
  type GlassStyle,
} from "expo-glass-effect";
import { usePreferences } from "@/preferences/PreferencesProvider";

export function GlassSurface({
  children,
  style,
  isInteractive = false,
  glassEffectStyle = "regular",
}: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  isInteractive?: boolean;
  glassEffectStyle?: GlassStyle;
}) {
  const { colors, dark } = usePreferences();
  if (isGlassEffectAPIAvailable()) {
    return (
      <GlassView
        glassEffectStyle={glassEffectStyle}
        colorScheme={dark ? "dark" : "light"}
        isInteractive={isInteractive}
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

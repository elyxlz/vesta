import type { ReactNode } from "react";
import { StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import { GlassView, isGlassEffectAPIAvailable } from "expo-glass-effect";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

interface CardProps {
  children: ReactNode;
  glass?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function Card({ children, glass = false, style }: CardProps) {
  const { colors, dark } = usePreferences();
  if (glass && isGlassEffectAPIAvailable()) {
    return (
      <GlassView
        glassEffectStyle="regular"
        colorScheme={dark ? "dark" : "light"}
        style={[styles.card, style]}
      >
        {children}
      </GlassView>
    );
  }
  return (
    <View
      style={[
        styles.card,
        { backgroundColor: colors.card, borderColor: colors.border },
        style,
      ]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radii.card,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 16,
    gap: 12,
    overflow: "hidden",
  },
});

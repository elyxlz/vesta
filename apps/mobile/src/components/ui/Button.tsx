import type { ComponentProps, ReactNode } from "react";
import { ActivityIndicator, Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";
import { Text } from "./Typography";

type IconName = ComponentProps<typeof Ionicons>["name"];
type ButtonVariant = "primary" | "secondary" | "danger" | "plain";
type ButtonSize = "default" | "small";

function withAlpha(color: string, opacity: number): string {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return color;
  const alpha = Math.round(opacity * 255)
    .toString(16)
    .padStart(2, "0");
  return `${color}${alpha}`;
}

interface ButtonProps {
  children: ReactNode;
  onPress: () => void;
  variant?: ButtonVariant;
  icon?: IconName;
  iconColor?: string;
  disabled?: boolean;
  loading?: boolean;
  pill?: boolean;
  size?: ButtonSize;
  accessibilityLabel?: string;
}

interface TextButtonProps {
  children: ReactNode;
  onPress: () => void;
  accessibilityLabel?: string;
}

export function Button({
  children,
  onPress,
  variant = "primary",
  icon,
  iconColor,
  disabled = false,
  loading = false,
  pill = false,
  size = "default",
  accessibilityLabel,
}: ButtonProps) {
  const { colors } = usePreferences();
  const backgroundColor =
    variant === "primary"
      ? colors.accent
      : variant === "danger"
        ? withAlpha(colors.danger, 0.7)
        : variant === "secondary"
          ? colors.input
          : "transparent";
  const textColor =
    variant === "primary"
      ? colors.accentText
      : variant === "danger"
        ? "#ffffff"
        : colors.text;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      disabled={disabled || loading}
      hitSlop={size === "small" ? 4 : undefined}
      onPress={() => {
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        onPress();
      }}
      style={({ pressed }) => [
        styles.button,
        size === "small" ? styles.smallButton : null,
        pill ? styles.pill : null,
        {
          backgroundColor:
            variant === "danger" && pressed
              ? withAlpha(colors.danger, 0.8)
              : backgroundColor,
          opacity: disabled ? 0.45 : pressed && variant !== "danger" ? 0.72 : 1,
        },
      ]}
    >
      {loading ? (
        <ActivityIndicator color={textColor} />
      ) : (
        <View style={styles.content}>
          {icon ? (
            <Ionicons name={icon} size={18} color={iconColor ?? textColor} />
          ) : null}
          <Text
            style={[
              styles.label,
              size === "small" ? styles.smallLabel : null,
              { color: textColor },
            ]}
          >
            {children}
          </Text>
        </View>
      )}
    </Pressable>
  );
}

export function TextButton({
  children,
  onPress,
  accessibilityLabel,
}: TextButtonProps) {
  const { colors } = usePreferences();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      hitSlop={4}
      onPress={onPress}
      style={({ pressed }) => [
        styles.textButton,
        { opacity: pressed ? 0.55 : 1 },
      ]}
    >
      <Text style={[styles.textButtonLabel, { color: colors.secondaryText }]}>
        {children}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 48,
    borderRadius: radii.button,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 18,
  },
  smallButton: { minHeight: 40, paddingHorizontal: 14 },
  pill: { borderRadius: radii.pill },
  content: { flexDirection: "row", alignItems: "center", gap: 8 },
  label: { fontSize: 16, fontWeight: "700" },
  smallLabel: { fontSize: 14, fontWeight: "600" },
  textButton: { alignSelf: "center", padding: 4 },
  textButtonLabel: { fontSize: 13, fontWeight: "500" },
});

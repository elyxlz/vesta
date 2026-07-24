import type { ComponentProps, ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  View,
  type StyleProp,
  type TextStyle,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";
import { Text } from "./Typography";

type IconName = ComponentProps<typeof Ionicons>["name"];
type ButtonVariant =
  | "primary"
  | "secondary"
  | "card"
  | "cardDanger"
  | "ghost"
  | "danger"
  | "plain";
type ButtonSize = "default" | "small" | "compact";

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
  iconSize?: number;
  disabled?: boolean;
  loading?: boolean;
  pill?: boolean;
  size?: ButtonSize;
  labelStyle?: StyleProp<TextStyle>;
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
  iconSize = 18,
  disabled = false,
  loading = false,
  pill = false,
  size = "default",
  labelStyle,
  accessibilityLabel,
}: ButtonProps) {
  const { colors } = usePreferences();
  const usesCardSurface = variant === "card" || variant === "cardDanger";
  const backgroundColor =
    variant === "primary"
      ? colors.accent
      : variant === "danger"
        ? withAlpha(colors.danger, 0.7)
        : usesCardSurface
          ? colors.card
          : variant === "secondary"
            ? colors.input
            : "transparent";
  const textColor =
    variant === "primary"
      ? colors.accentText
      : variant === "danger"
        ? "#ffffff"
        : variant === "cardDanger"
          ? colors.danger
          : colors.text;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      disabled={disabled || loading}
      hitSlop={size === "compact" ? 13 : size === "small" ? 4 : undefined}
      onPress={() => {
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        onPress();
      }}
      style={({ pressed }) => [
        styles.button,
        size === "small"
          ? styles.smallButton
          : size === "compact"
            ? styles.compactButton
            : null,
        usesCardSurface ? styles.cardButton : null,
        pill ? styles.pill : null,
        {
          backgroundColor:
            variant === "danger" && pressed
              ? withAlpha(colors.danger, 0.8)
              : backgroundColor,
          borderColor: usesCardSurface ? colors.border : "transparent",
          borderWidth: usesCardSurface ? StyleSheet.hairlineWidth : 0,
          opacity: disabled
            ? 0.45
            : pressed && variant !== "danger" && variant !== "ghost"
              ? 0.72
              : 1,
        },
      ]}
    >
      {({ pressed }) => {
        const contentColor =
          variant === "ghost" && pressed ? colors.interactive : textColor;

        return loading ? (
          <ActivityIndicator color={contentColor} />
        ) : (
          <View
            style={[
              styles.content,
              usesCardSurface ? styles.cardContent : null,
            ]}
          >
            {icon ? (
              <Ionicons
                name={icon}
                size={iconSize}
                color={iconColor ?? contentColor}
              />
            ) : null}
            <Text
              style={[
                styles.label,
                size !== "default" ? styles.smallLabel : null,
                usesCardSurface ? styles.cardLabel : null,
                labelStyle,
                { color: contentColor },
              ]}
            >
              {children}
            </Text>
            {usesCardSurface ? (
              <Ionicons
                name="chevron-forward"
                size={17}
                color={colors.tertiaryText}
              />
            ) : null}
          </View>
        );
      }}
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
  compactButton: { minHeight: 18, paddingHorizontal: 14 },
  cardButton: { alignItems: "flex-start", paddingHorizontal: 16 },
  pill: { borderRadius: radii.pill },
  content: { flexDirection: "row", alignItems: "center", gap: 8 },
  cardContent: { alignSelf: "stretch" },
  label: { fontSize: 16, fontWeight: "700" },
  smallLabel: { fontSize: 14, fontWeight: "600" },
  cardLabel: { flex: 1, fontSize: 16, fontWeight: "600" },
  textButton: { alignSelf: "center", padding: 4 },
  textButtonLabel: { fontSize: 13, fontWeight: "500" },
});

import {
  StyleSheet,
  Text as NativeText,
  TextInput as NativeTextInput,
  type TextInputProps,
  type TextProps,
  type TextStyle,
} from "react-native";
import type { Ref } from "react";
import { fontNames } from "@/theme/typography";

export type FontFamily = "sans" | "heading" | "wordmark" | "mono";

function numericWeight(weight: TextStyle["fontWeight"]): number {
  if (typeof weight === "number") return weight;
  if (weight === "bold") return 700;
  if (weight && /^\d+$/.test(weight)) return Number(weight);
  return 400;
}

function fontFor(family: FontFamily, weight: TextStyle["fontWeight"]): string {
  const value = numericWeight(weight);
  if (family === "wordmark") {
    return process.env.EXPO_OS === "ios"
      ? fontNames.wordmark.native.ios
      : fontNames.wordmark.native.default;
  }
  if (family === "heading") {
    if (value >= 700) return fontNames.heading.native["700"];
    if (value >= 600) return fontNames.heading.native["600"];
    if (value >= 500) return fontNames.heading.native["500"];
    return fontNames.heading.native["400"];
  }
  if (family === "mono") {
    if (value >= 700) return fontNames.mono.native["700"];
    if (value >= 600) return fontNames.mono.native["600"];
    return fontNames.mono.native["400"];
  }
  if (value >= 900) return fontNames.sans.native["900"];
  if (value >= 800) return fontNames.sans.native["800"];
  if (value >= 700) return fontNames.sans.native["700"];
  if (value >= 600) return fontNames.sans.native["600"];
  if (value >= 500) return fontNames.sans.native["500"];
  return fontNames.sans.native["400"];
}

function themedStyle(
  style: TextProps["style"] | TextInputProps["style"],
  family: FontFamily,
): TextStyle {
  const flattened = StyleSheet.flatten(style) ?? {};
  return {
    ...flattened,
    fontFamily: fontFor(family, flattened.fontWeight),
    fontWeight: family === "wordmark" ? flattened.fontWeight : undefined,
  };
}

export function Text({
  family = "sans",
  style,
  ...props
}: TextProps & { family?: FontFamily }) {
  return <NativeText {...props} style={themedStyle(style, family)} />;
}

export function TextInput({
  family = "sans",
  ref,
  style,
  ...props
}: TextInputProps & {
  family?: FontFamily;
  ref?: Ref<NativeTextInput>;
}) {
  return (
    <NativeTextInput
      ref={ref}
      {...props}
      style={themedStyle(style, family)}
    />
  );
}

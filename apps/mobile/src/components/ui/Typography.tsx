import {
  StyleSheet,
  Text as NativeText,
  TextInput as NativeTextInput,
  type TextInputProps,
  type TextProps,
  type TextStyle,
} from "react-native";
import type { ReactNode, Ref } from "react";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { fontNames } from "@/theme/typography";

export type FontFamily = "sans" | "heading" | "serif" | "wordmark" | "mono";

function numericWeight(weight: TextStyle["fontWeight"]): number {
  if (typeof weight === "number") return weight;
  if (weight === "bold") return 700;
  if (weight && /^\d+$/.test(weight)) return Number(weight);
  return 400;
}

type NamedFamily = Exclude<FontFamily, "sans" | "heading">;

// The loaded face of a named family at the nearest weight it ships.
function faceFor(family: NamedFamily, weight: TextStyle["fontWeight"]): string {
  const value = numericWeight(weight);
  if (family === "mono") {
    if (value >= 700) return fontNames.mono.native["700"];
    if (value >= 600) return fontNames.mono.native["600"];
    return fontNames.mono.native["400"];
  }
  const faces = fontNames[family].native;
  if (value >= 700) return faces["700"];
  if (value >= 600) return faces["600"];
  if (value >= 500) return faces["500"];
  return faces["400"];
}

// Sans and heading text is the system font, which takes its weight from
// `fontWeight`. A named family is one loaded face per weight, so the face
// name carries the weight.
function themedStyle(
  style: TextProps["style"] | TextInputProps["style"],
  family: FontFamily,
): TextStyle {
  const flattened = StyleSheet.flatten(style) ?? {};
  if (family === "sans" || family === "heading") {
    return { ...flattened, fontFamily: undefined };
  }
  return {
    ...flattened,
    fontFamily: faceFor(family, flattened.fontWeight),
    fontWeight: undefined,
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
    <NativeTextInput ref={ref} {...props} style={themedStyle(style, family)} />
  );
}

// An example phrase the user could say, set apart inside running copy: the serif voice in the
// foreground color, so a quoted prompt reads as a voice rather than more instructions.
export function Quote({ children }: { children: ReactNode }) {
  const { colors } = usePreferences();
  return (
    <Text family="serif" style={[styles.quote, { color: colors.text }]}>
      {children}
    </Text>
  );
}

const styles = StyleSheet.create({
  quote: { fontWeight: "500" },
});

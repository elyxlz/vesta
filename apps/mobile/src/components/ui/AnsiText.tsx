import { memo, useMemo } from "react";
import type { TextProps, TextStyle } from "react-native";
import { parseAnsi, resolveAnsiColor, type AnsiStyle } from "@/lib/ansi";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { Text } from "./Typography";

interface AnsiTextProps extends Omit<TextProps, "children"> {
  value: string;
}

function decoration(style: AnsiStyle): TextStyle["textDecorationLine"] {
  if (style.underline && style.strikethrough) return "underline line-through";
  if (style.underline) return "underline";
  if (style.strikethrough) return "line-through";
  return "none";
}

export const AnsiText = memo(function AnsiText({
  value,
  style,
  ...props
}: AnsiTextProps) {
  const { colors, dark } = usePreferences();
  const spans = useMemo(() => parseAnsi(value), [value]);
  const palette = useMemo(
    () => [
      colors.text,
      colors.danger,
      colors.success,
      colors.warning,
      dark ? "#60a5fa" : "#2563eb",
      dark ? "#d8a4ff" : "#9333ea",
      dark ? "#67e8f9" : "#087e8b",
      colors.secondaryText,
      colors.tertiaryText,
      dark ? "#ff8a8c" : "#c0000a",
      dark ? "#6ee77b" : "#1f7a2c",
      dark ? "#ffd45c" : "#9a4d00",
      dark ? "#93c5fd" : "#1d4ed8",
      dark ? "#e9a8ff" : "#7e22ce",
      dark ? "#a5f3fc" : "#0e7490",
      colors.text,
    ],
    [colors, dark],
  );

  return (
    <Text
      {...props}
      family="mono"
      style={[{ color: colors.secondaryText }, style]}
    >
      {spans.map((span, index) => {
        let color = span.style.foreground
          ? resolveAnsiColor(span.style.foreground, palette)
          : colors.secondaryText;
        let backgroundColor = span.style.background
          ? resolveAnsiColor(span.style.background, palette)
          : undefined;
        if (span.style.inverse) {
          const previousColor = color;
          color = backgroundColor ?? colors.background;
          backgroundColor = previousColor;
        }
        return (
          <Text
            key={index}
            family="mono"
            style={{
              color: span.style.hidden ? "transparent" : color,
              backgroundColor,
              fontWeight: span.style.bold ? "700" : "400",
              fontStyle: span.style.italic ? "italic" : "normal",
              opacity: span.style.dim ? 0.62 : 1,
              textDecorationLine: decoration(span.style),
            }}
          >
            {span.text}
          </Text>
        );
      })}
    </Text>
  );
});

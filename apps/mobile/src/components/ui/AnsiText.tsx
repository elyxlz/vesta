import { memo, useMemo } from "react";
import type { TextProps, TextStyle } from "react-native";
import { parseAnsi, resolveAnsiColor, type AnsiStyle } from "@vesta/core";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { designTokens } from "@/theme/generated";
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
  const palette = useMemo(() => {
    const terminal = dark
      ? designTokens.colors.dark
      : designTokens.colors.light;
    return [
      terminal["ansi-black"],
      terminal["ansi-red"],
      terminal["ansi-green"],
      terminal["ansi-yellow"],
      terminal["ansi-blue"],
      terminal["ansi-magenta"],
      terminal["ansi-cyan"],
      terminal["ansi-white"],
      terminal["ansi-bright-black"],
      terminal["ansi-bright-red"],
      terminal["ansi-bright-green"],
      terminal["ansi-bright-yellow"],
      terminal["ansi-bright-blue"],
      terminal["ansi-bright-magenta"],
      terminal["ansi-bright-cyan"],
      terminal["ansi-bright-white"],
    ];
  }, [dark]);

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

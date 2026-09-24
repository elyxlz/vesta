import { Fragment, memo, useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";
import * as Clipboard from "expo-clipboard";
import { CODE_TOKEN_COLORS, highlightCode } from "@vesta/core";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { designTokens } from "@/theme/generated";
import { fontNames } from "@/theme/typography";

const COPIED_MS = 1500;

export const CodeBlock = memo(function CodeBlock({
  code,
  info,
  onLongPress,
}: {
  code: string;
  info: string | null;
  onLongPress?: () => void;
}) {
  const { colors, dark } = usePreferences();
  const highlighted = useMemo(() => highlightCode(code, info), [code, info]);
  const [copied, setCopied] = useState(false);
  const palette = dark ? designTokens.colors.dark : designTokens.colors.light;
  const copy = () => {
    void Clipboard.setStringAsync(code).then(() => {
      setCopied(true);
      setTimeout(() => {
        setCopied(false);
      }, COPIED_MS);
    });
  };
  return (
    <Pressable
      onLongPress={onLongPress}
      style={[
        styles.frame,
        { backgroundColor: colors.code, borderColor: colors.border },
      ]}
    >
      <View style={styles.header}>
        <Text style={[styles.label, { color: colors.tertiaryText }]}>
          {highlighted.language ?? "code"}
        </Text>
        <Pressable accessibilityRole="button" hitSlop={10} onPress={copy}>
          <Text style={[styles.label, { color: colors.secondaryText }]}>
            {copied ? "Copied" : "Copy"}
          </Text>
        </Pressable>
      </View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
      >
        <Text style={[styles.code, { color: colors.text }]}>
          {highlighted.lines.map((line, lineIndex) => (
            <Fragment key={lineIndex}>
              {lineIndex > 0 ? "\n" : null}
              {line.map((token, tokenIndex) => (
                <Text
                  key={tokenIndex}
                  style={{ color: palette[CODE_TOKEN_COLORS[token.kind]] }}
                >
                  {token.text}
                </Text>
              ))}
            </Fragment>
          ))}
        </Text>
      </ScrollView>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  frame: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 11,
    borderCurve: "continuous",
    marginVertical: 6,
    overflow: "hidden",
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12,
    paddingHorizontal: 10,
    paddingTop: 6,
  },
  label: { fontSize: 12, lineHeight: 16 },
  scroll: { flexGrow: 0, maxWidth: "100%" },
  scrollContent: { paddingHorizontal: 10, paddingTop: 4, paddingBottom: 9 },
  code: {
    fontFamily: fontNames.mono.native["400"],
    fontSize: 13,
    lineHeight: 19,
  },
});

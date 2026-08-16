import { StyleSheet } from "react-native";
import type { AppColors } from "@/theme/colors";
import { fontNames } from "@/theme/typography";

function buildMarkdownStyles(colors: AppColors) {
  return {
    body: {
      color: colors.text,
      fontFamily: fontNames.sans.native["400"],
      fontSize: 16,
      lineHeight: 23,
    },
    heading1: {
      color: colors.text,
      fontFamily: fontNames.heading.native["600"],
      fontSize: 22,
      lineHeight: 27,
      marginTop: 5,
      marginBottom: 8,
    },
    heading2: {
      color: colors.text,
      fontFamily: fontNames.heading.native["600"],
      fontSize: 20,
      lineHeight: 25,
      marginTop: 5,
      marginBottom: 7,
    },
    heading3: {
      color: colors.text,
      fontFamily: fontNames.heading.native["600"],
      fontSize: 18,
      lineHeight: 23,
      marginTop: 4,
      marginBottom: 6,
    },
    heading4: {
      color: colors.text,
      fontFamily: fontNames.sans.native["600"],
      fontSize: 16,
      lineHeight: 22,
      marginTop: 3,
      marginBottom: 5,
    },
    heading5: {
      color: colors.secondaryText,
      fontFamily: fontNames.sans.native["600"],
      fontSize: 15,
      lineHeight: 21,
      marginTop: 3,
      marginBottom: 4,
    },
    heading6: {
      color: colors.secondaryText,
      fontFamily: fontNames.sans.native["600"],
      fontSize: 13,
      lineHeight: 18,
      marginTop: 3,
      marginBottom: 4,
      textTransform: "uppercase" as const,
      letterSpacing: 0.4,
    },
    strong: { fontFamily: fontNames.sans.native["600"] },
    em: { fontStyle: "italic" as const },
    s: {
      color: colors.tertiaryText,
      textDecorationLine: "line-through" as const,
    },
    paragraph: { marginTop: 0, marginBottom: 8 },
    link: {
      color: colors.interactive,
      fontFamily: fontNames.sans.native["500"],
      textDecorationLine: "underline" as const,
      textDecorationColor: colors.interactive,
    },
    blocklink: { borderBottomWidth: 0 },
    blockquote: {
      color: colors.secondaryText,
      fontFamily: fontNames.sans.native["400"],
      fontSize: 13,
      lineHeight: 17,
    },
    bullet_list: { marginTop: 1, marginBottom: 7 },
    ordered_list: { marginTop: 1, marginBottom: 7 },
    list_item: { marginBottom: 3 },
    bullet_list_icon: {
      color: colors.secondaryText,
      width: 16,
      marginLeft: 1,
      marginRight: 4,
      fontSize: 17,
      lineHeight: 23,
    },
    ordered_list_icon: {
      color: colors.secondaryText,
      minWidth: 20,
      marginLeft: 0,
      marginRight: 5,
      fontFamily: fontNames.sans.native["500"],
      fontSize: 14,
      lineHeight: 23,
      textAlign: "right" as const,
      fontVariant: ["tabular-nums"] as const,
    },
    bullet_list_content: { flex: 1 },
    ordered_list_content: { flex: 1 },
    code_inline: {
      color: colors.text,
      fontFamily: fontNames.mono.native["400"],
      fontSize: 14,
      lineHeight: 20,
      backgroundColor: colors.code,
      borderWidth: 0,
      borderRadius: 5,
      paddingHorizontal: 4,
      paddingVertical: 1,
    },
    code_block: {
      color: colors.text,
      fontFamily: fontNames.mono.native["400"],
      fontSize: 13,
      lineHeight: 19,
      backgroundColor: colors.code,
      borderColor: colors.border,
      borderWidth: StyleSheet.hairlineWidth,
      borderRadius: 11,
      borderCurve: "continuous" as const,
      marginVertical: 6,
      padding: 10,
    },
    fence: {
      color: colors.text,
      fontFamily: fontNames.mono.native["400"],
      fontSize: 13,
      lineHeight: 19,
      backgroundColor: colors.code,
      borderColor: colors.border,
      borderWidth: StyleSheet.hairlineWidth,
      borderRadius: 11,
      borderCurve: "continuous" as const,
      marginVertical: 6,
      padding: 10,
    },
    hr: {
      height: StyleSheet.hairlineWidth,
      backgroundColor: colors.border,
      marginVertical: 11,
    },
    table: {
      borderColor: colors.border,
      borderWidth: StyleSheet.hairlineWidth,
      borderRadius: 9,
      borderCurve: "continuous" as const,
      marginVertical: 7,
      overflow: "hidden" as const,
    },
    thead: { backgroundColor: colors.input },
    tr: {
      borderBottomColor: colors.border,
      borderBottomWidth: StyleSheet.hairlineWidth,
    },
    th: { paddingHorizontal: 7, paddingVertical: 6 },
    td: { paddingHorizontal: 7, paddingVertical: 6 },
    image: {
      flex: 1,
      borderRadius: 11,
      borderCurve: "continuous" as const,
      marginVertical: 6,
      overflow: "hidden" as const,
    },
  };
}

export type ChatMarkdownStyles = ReturnType<typeof buildMarkdownStyles>;

export interface ChatMarkdownStyleSet {
  base: ChatMarkdownStyles;
  user: ChatMarkdownStyles;
}

const styleSetsByPalette = new Map<AppColors, ChatMarkdownStyleSet>();

// One frozen style tree per palette (dark and light), so every chat row
// shares the same objects instead of rebuilding the tree per render.
export function chatMarkdownStyleSet(colors: AppColors): ChatMarkdownStyleSet {
  const cached = styleSetsByPalette.get(colors);
  if (cached) return cached;
  const base = Object.freeze(buildMarkdownStyles(colors));
  const user = Object.freeze({
    ...base,
    body: { ...base.body, color: colors.accentText },
    link: {
      ...base.link,
      color: colors.accentText,
      textDecorationColor: colors.accentText,
    },
  });
  const styleSet = Object.freeze({ base, user });
  styleSetsByPalette.set(colors, styleSet);
  return styleSet;
}

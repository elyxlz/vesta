import { StyleSheet } from "react-native";
import { darkColors, lightColors, type AppColors } from "@/theme/colors";
import { fontNames } from "@/theme/typography";

// A column, not the library's row: a heading's text in a row is measured at its
// one-line width on Android and overflows the bubble instead of wrapping.
const HEADING_LAYOUT = {
  flexDirection: "column" as const,
  flexWrap: "nowrap" as const,
};
// A cell keeps the library's flex 1, so every row splits its width into the
// same columns, but a zero basis adds nothing to a shrink-to-fit bubble: the
// minimum width is what gives a table-only bubble its width.
const TABLE_CELL_MIN_WIDTH = 72;
// FitImage takes its height from its laid-out width, so a zero-width image in
// a shrink-to-fit bubble has no height either.
const IMAGE_MIN_WIDTH = 200;

function buildMarkdownStyles(colors: AppColors) {
  return {
    body: {
      color: colors.text,
      fontFamily: fontNames.sans.native["400"],
      fontSize: 16,
      lineHeight: 23,
    },
    heading1: {
      ...HEADING_LAYOUT,
      color: colors.text,
      fontFamily: fontNames.heading.native["600"],
      fontSize: 20,
      lineHeight: 25,
      marginTop: 5,
      marginBottom: 6,
    },
    heading2: {
      ...HEADING_LAYOUT,
      color: colors.text,
      fontFamily: fontNames.heading.native["600"],
      fontSize: 18,
      lineHeight: 23,
      marginTop: 5,
      marginBottom: 5,
    },
    heading3: {
      ...HEADING_LAYOUT,
      color: colors.text,
      fontFamily: fontNames.heading.native["600"],
      fontSize: 16,
      lineHeight: 22,
      marginTop: 4,
      marginBottom: 4,
    },
    heading4: {
      ...HEADING_LAYOUT,
      color: colors.secondaryText,
      fontFamily: fontNames.sans.native["600"],
      fontSize: 15,
      lineHeight: 21,
      marginTop: 3,
      marginBottom: 4,
    },
    heading5: {
      ...HEADING_LAYOUT,
      color: colors.secondaryText,
      fontFamily: fontNames.sans.native["600"],
      fontSize: 15,
      lineHeight: 21,
      marginTop: 3,
      marginBottom: 4,
    },
    heading6: {
      ...HEADING_LAYOUT,
      color: colors.secondaryText,
      fontFamily: fontNames.sans.native["600"],
      fontSize: 15,
      lineHeight: 21,
      marginTop: 3,
      marginBottom: 4,
    },
    strong: { fontFamily: fontNames.sans.native["600"] },
    em: { fontStyle: "italic" as const },
    s: {
      color: colors.tertiaryText,
      textDecorationLine: "line-through" as const,
    },
    // A column, not the library's wrapping row: the textgroup rule folds a paragraph into one
    // Text, and a Text inside a wrapping row is measured at its one-line width on Android and
    // overflows instead of wrapping.
    paragraph: {
      marginTop: 0,
      marginBottom: 8,
      flexDirection: "column" as const,
      flexWrap: "nowrap" as const,
    },
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
    // An auto basis, not the library's flex 1 (basis 0): a zero basis adds nothing to a
    // shrink-to-fit bubble's width, so a bubble holding only a list item collapsed to its
    // marker and laid the text out at zero width. minWidth 0 lets the text still shrink.
    bullet_list_content: {
      flexGrow: 1,
      flexShrink: 1,
      flexBasis: "auto" as const,
      minWidth: 0,
    },
    ordered_list_content: {
      flexGrow: 1,
      flexShrink: 1,
      flexBasis: "auto" as const,
      minWidth: 0,
    },
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
      flexGrow: 1,
      marginVertical: 7,
      overflow: "hidden" as const,
    },
    thead: { backgroundColor: colors.input },
    tr: {
      borderBottomColor: colors.border,
      borderBottomWidth: StyleSheet.hairlineWidth,
    },
    th: {
      minWidth: TABLE_CELL_MIN_WIDTH,
      paddingHorizontal: 7,
      paddingVertical: 6,
    },
    td: {
      minWidth: TABLE_CELL_MIN_WIDTH,
      paddingHorizontal: 7,
      paddingVertical: 6,
    },
    image: {
      flex: 1,
      minWidth: IMAGE_MIN_WIDTH,
      borderRadius: 11,
      borderCurve: "continuous" as const,
      marginVertical: 6,
      overflow: "hidden" as const,
    },
  };
}

type ChatMarkdownStyles = ReturnType<typeof buildMarkdownStyles>;

export interface ChatMarkdownStyleSet {
  base: ChatMarkdownStyles;
  user: ChatMarkdownStyles;
}

function buildStyleSet(colors: AppColors): ChatMarkdownStyleSet {
  const base = buildMarkdownStyles(colors);
  return {
    base,
    user: {
      ...base,
      body: { ...base.body, color: colors.accentText },
      blockquote: { ...base.blockquote, color: colors.accentText },
      link: {
        ...base.link,
        color: colors.accentText,
        textDecorationColor: colors.accentText,
      },
    },
  };
}

// One style tree per palette, built once, so every chat row shares the same
// objects instead of rebuilding the tree per render.
const DARK_STYLE_SET = buildStyleSet(darkColors);
const LIGHT_STYLE_SET = buildStyleSet(lightColors);

export function chatMarkdownStyleSet(colors: AppColors): ChatMarkdownStyleSet {
  return colors === darkColors ? DARK_STYLE_SET : LIGHT_STYLE_SET;
}

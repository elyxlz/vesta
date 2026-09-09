import { radii } from "@/theme/layout";
import { fontNames } from "@/theme/typography";

// react-native-screens draws Android form sheets with square corners by
// default (sheetCornerRadius 0); iOS keeps the native system sheet radius.
export const formSheetCorners: { sheetCornerRadius?: number } =
  process.env.EXPO_OS === "android" ? { sheetCornerRadius: radii.card } : {};

// Native stack titles and Android's in-content sheet titles share this style.
export const headerTitleStyle = {
  fontFamily: fontNames.heading.native["500"],
  fontSize: 20,
  fontWeight: "500",
} as const;

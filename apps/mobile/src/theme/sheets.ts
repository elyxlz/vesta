import { radii } from "@/theme/layout";
import { fontNames } from "@/theme/typography";

// react-native-screens draws Android form sheets with square corners by
// default (sheetCornerRadius 0); iOS keeps the native system sheet radius.
export const formSheetCorners: { sheetCornerRadius?: number } =
  process.env.EXPO_OS === "android" ? { sheetCornerRadius: radii.card } : {};

// The one title style every stack header and sheet header shares: the heading serif.
export const headerTitleStyle = {
  fontFamily: fontNames.heading.native["500"],
  fontSize: 24,
  fontWeight: "500",
} as const;

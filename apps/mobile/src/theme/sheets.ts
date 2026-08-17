import { radii } from "@/theme/layout";

// react-native-screens draws Android form sheets with square corners by
// default (sheetCornerRadius 0); iOS keeps the native system sheet radius.
export const formSheetCorners: { sheetCornerRadius?: number } =
  process.env.EXPO_OS === "android" ? { sheetCornerRadius: radii.card } : {};

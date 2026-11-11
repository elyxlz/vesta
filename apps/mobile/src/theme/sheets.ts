import type { NativeStackNavigationOptions } from "expo-router";
import type { AppColors } from "@/theme/colors";
import { radii } from "@/theme/layout";
import { fontNames } from "@/theme/typography";

const IS_ANDROID = process.env.EXPO_OS === "android";

// react-native-screens draws Android form sheets with square corners by
// default (sheetCornerRadius 0); iOS keeps the native system sheet radius.
const formSheetCorners: { sheetCornerRadius?: number } = IS_ANDROID
  ? { sheetCornerRadius: radii.card }
  : {};

// Native stack titles and Android's in-content sheet titles share this style.
export const headerTitleStyle = {
  fontFamily: fontNames.heading.native["500"],
  fontSize: 20,
  fontWeight: "500",
} as const;

// Every screen that renders an AuthSheet presents with these options, so the
// sheet surface behind the content always matches the card it draws.
export function authSheetOptions(
  colors: AppColors,
): NativeStackNavigationOptions {
  return {
    headerShown: false,
    presentation: "formSheet",
    ...formSheetCorners,
    sheetAllowedDetents: "fitToContents",
    sheetGrabberVisible: false,
    contentStyle: { backgroundColor: colors.card },
  };
}

// A sheet that asks for a decision the user cannot dismiss: Android shows it
// as a full screen, iOS as an auth sheet with the swipe-down gesture off.
export function blockingSheetOptions(
  colors: AppColors,
): NativeStackNavigationOptions {
  return IS_ANDROID
    ? {
        headerShown: false,
        animation: "none",
        gestureEnabled: false,
        contentStyle: { backgroundColor: colors.background },
      }
    : { ...authSheetOptions(colors), gestureEnabled: false };
}

// A long page in a sheet that opens at half height on iOS. Android's collapsed
// multi-detent sheet can measure only its header, so it opens at full height.
export function resizableSheetOptions(
  colors: AppColors,
): NativeStackNavigationOptions {
  return {
    presentation: "formSheet",
    ...formSheetCorners,
    sheetAllowedDetents: IS_ANDROID ? [1] : [0.5, 1],
    sheetInitialDetentIndex: 0,
    sheetGrabberVisible: !IS_ANDROID,
    sheetExpandsWhenScrolledToEdge: true,
    contentStyle: { backgroundColor: colors.background },
  };
}

// A sheet that always fills the screen, for content that must lay out against
// the full height.
export function fullSheetOptions(
  colors: AppColors,
): NativeStackNavigationOptions {
  return {
    presentation: "formSheet",
    ...formSheetCorners,
    sheetAllowedDetents: [1],
    sheetGrabberVisible: false,
    sheetExpandsWhenScrolledToEdge: false,
    contentStyle: { backgroundColor: colors.background },
  };
}

// The transparent native header every stack draws over its content.
export function stackHeaderOptions(
  colors: AppColors,
): NativeStackNavigationOptions {
  return {
    contentStyle: { backgroundColor: colors.background },
    headerTransparent: true,
    headerStyle: { backgroundColor: "transparent" },
    headerTintColor: colors.text,
    headerTitleStyle,
    headerShadowVisible: false,
    headerBackButtonDisplayMode: "minimal",
  };
}

import { useSafeAreaInsets } from "react-native-safe-area-context";

const IS_IOS = process.env.EXPO_OS === "ios";

// Single owner of the bottom-edge decision: iOS surfaces float above the
// home indicator (form sheets) or inset automatically (scroll views),
// while Android surfaces reach the screen bottom, so the gesture inset
// joins the base padding there.
export function useBottomInset(base: number): number {
  const insets = useSafeAreaInsets();
  return IS_IOS ? base : base + insets.bottom;
}

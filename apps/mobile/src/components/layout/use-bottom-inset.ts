import { useSafeAreaInsets } from "react-native-safe-area-context";

const IS_IOS = process.env.EXPO_OS === "ios";
// Android gesture navigation reports a thin bottom inset, so surfaces sit
// closer to the edge than on iOS, where the OS floats them above the home
// indicator. Clamp the Android bottom to that indicator's height so gesture
// layouts keep the same gap; the 3-button bar already exceeds it, and iOS
// passes its own inset through (0 on home-button devices).
const ANDROID_MIN_BOTTOM_GAP = 34;

// The bottom-edge clearance a surface leaves above the system gesture area or
// navigation bar.
export function useBottomGap(): number {
  const insets = useSafeAreaInsets();
  return IS_IOS ? insets.bottom : Math.max(insets.bottom, ANDROID_MIN_BOTTOM_GAP);
}

// Single owner of the bottom-edge decision: iOS surfaces float above the
// home indicator (form sheets) or inset automatically (scroll views), while
// Android surfaces reach the screen bottom, so the gap joins the base padding
// there.
export function useBottomInset(base: number): number {
  const gap = useBottomGap();
  return IS_IOS ? base : base + gap;
}

import type { ReactNode } from "react";
import {
  SafeAreaInsetsContext,
  useSafeAreaInsets,
} from "react-native-safe-area-context";

const IS_ANDROID = process.env.EXPO_OS === "android";
// iOS floats content above the home indicator; Android gesture navigation
// reports a thinner bottom inset, so surfaces sit closer to the edge. Clamp
// the Android bottom to this floor so every safe-area consumer keeps a
// comfortable, iOS-like gap. The 3-button bar reports a larger inset and
// passes through unchanged.
const GESTURE_BOTTOM_GAP = 48;

// Single owner of the Android bottom-inset adjustment: it re-provides the
// safe-area context once, above every screen, so useSafeAreaInsets and
// SafeAreaView see the clamped value everywhere.
export function AndroidBottomInset({ children }: { children: ReactNode }) {
  const insets = useSafeAreaInsets();
  if (!IS_ANDROID) return children;
  const adjusted = {
    ...insets,
    bottom: Math.max(insets.bottom, GESTURE_BOTTOM_GAP),
  };
  return (
    <SafeAreaInsetsContext.Provider value={adjusted}>
      {children}
    </SafeAreaInsetsContext.Provider>
  );
}

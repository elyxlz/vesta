import { useMemo, type ReactNode } from "react";
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
// safe-area context once, above every screen, so every useSafeAreaInsets
// consumer sees the clamped value. Memoized on the insets so an unrelated
// re-render never re-identifies the context and re-renders every consumer.
export function AndroidBottomInset({ children }: { children: ReactNode }) {
  const insets = useSafeAreaInsets();
  const adjusted = useMemo(
    () => ({ ...insets, bottom: Math.max(insets.bottom, GESTURE_BOTTOM_GAP) }),
    [insets],
  );
  if (!IS_ANDROID) return children;
  return (
    <SafeAreaInsetsContext.Provider value={adjusted}>
      {children}
    </SafeAreaInsetsContext.Provider>
  );
}

import { StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { navHeaderHeight } from "@/theme/layout";

const IS_IOS = process.env.EXPO_OS === "ios";
const HEADER_FADE_EXTENT = 32;

// iOS fades scrolling content under its transparent header natively;
// Android draws nothing there, so this gradient mirrors that scroll-edge
// fade: solid through the status bar and header zone, fading out below.
export function HeaderFade() {
  const insets = useSafeAreaInsets();
  const { colors } = usePreferences();
  if (IS_IOS) return null;
  const solid = insets.top + navHeaderHeight;
  const height = solid + HEADER_FADE_EXTENT;
  return (
    <LinearGradient
      pointerEvents="none"
      colors={[colors.background, colors.background, `${colors.background}00`]}
      locations={[0, solid / height, 1]}
      style={[styles.fade, { height }]}
    />
  );
}

const styles = StyleSheet.create({
  fade: {
    position: "absolute",
    zIndex: 1,
    top: 0,
    left: 0,
    right: 0,
  },
});

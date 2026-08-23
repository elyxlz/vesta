import { useEffect, type ReactNode } from "react";
import { BackHandler, StyleSheet, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { VestaBrand } from "@/components/VestaBrand";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

// Android form sheets live inside the app view hierarchy, where the
// BlockingSheetGateView backdrop paints over them, so the blocking gates
// present full screen instead: the same brand hero above a Material 3
// bottom card holding the sheet content, behind a scrim matching the
// dimming UIKit paints under an iOS form sheet in each appearance.
const SCRIM_COLOR_LIGHT = "rgba(0, 0, 0, 0.2)";
const SCRIM_COLOR_DARK = "rgba(0, 0, 0, 0.45)";

export function SheetGateScreen({ children }: { children: ReactNode }) {
  const insets = useSafeAreaInsets();
  const { colors, dark } = usePreferences();
  // The hardware back button must not pop a blocking gate: the owning gate would only re-push it
  // with animation "none", blinking the screen. Programmatic dismissal stays untouched.
  useEffect(() => {
    const subscription = BackHandler.addEventListener(
      "hardwareBackPress",
      () => true,
    );
    return () => {
      subscription.remove();
    };
  }, []);

  return (
    <View style={[styles.root, { backgroundColor: colors.background }]}>
      <StatusBar style={dark ? "light" : "dark"} />
      <View style={[styles.hero, { paddingTop: insets.top }]}>
        <VestaBrand />
      </View>
      <View
        pointerEvents="none"
        style={[
          styles.scrim,
          { backgroundColor: dark ? SCRIM_COLOR_DARK : SCRIM_COLOR_LIGHT },
        ]}
      />
      <View style={[styles.card, { backgroundColor: colors.card }]}>
        {children}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  hero: {
    flex: 1,
    minHeight: 220,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
  },
  card: {
    borderTopLeftRadius: radii.card,
    borderTopRightRadius: radii.card,
    overflow: "hidden",
  },
  scrim: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  },
});

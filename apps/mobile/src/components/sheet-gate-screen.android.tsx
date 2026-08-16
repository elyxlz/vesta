import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { VestaBrand } from "@/components/VestaBrand";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

// Android form sheets live inside the app view hierarchy, where the
// BlockingSheetGateView backdrop paints over them, so the blocking gates
// present full screen instead: the same brand hero above a Material 3
// bottom card holding the sheet content, behind a modal-bottom-sheet scrim.
const SCRIM_COLOR = "rgba(0, 0, 0, 0.32)";

export function SheetGateScreen({ children }: { children: ReactNode }) {
  const insets = useSafeAreaInsets();
  const { colors, dark } = usePreferences();

  return (
    <View style={[styles.root, { backgroundColor: colors.background }]}>
      <StatusBar style={dark ? "light" : "dark"} />
      <View style={[styles.hero, { paddingTop: insets.top }]}>
        <VestaBrand />
        <View pointerEvents="none" style={styles.scrim} />
      </View>
      <View
        style={[
          styles.card,
          {
            backgroundColor: colors.card,
            paddingBottom: insets.bottom,
          },
        ]}
      >
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
    backgroundColor: SCRIM_COLOR,
  },
});

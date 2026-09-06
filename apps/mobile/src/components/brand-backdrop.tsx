import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { VestaBrand } from "@/components/VestaBrand";
import { usePreferences } from "@/preferences/PreferencesProvider";

// Sheets overlay the page; their height must never reposition the brand.
// Center the whole lockup in the full page, not the space above a sheet.
export function BrandBackdrop({ orb }: { orb?: ReactNode }) {
  const { colors } = usePreferences();
  return (
    <View
      pointerEvents="none"
      style={[styles.backdrop, { backgroundColor: colors.background }]}
    >
      <VestaBrand orb={orb} />
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    position: "absolute",
    inset: 0,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
  },
});

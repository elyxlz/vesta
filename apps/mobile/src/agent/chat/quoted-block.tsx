import type { ReactNode } from "react";
import { StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import { usePreferences } from "@/preferences/PreferencesProvider";

// One owner for the quoted-block frame: the composer's reply preview and the
// transcript's markdown blockquote render the same accent-bar chip.
export function QuotedBlock({
  children,
  trailing,
  style,
}: {
  children: ReactNode;
  trailing?: ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  const { colors } = usePreferences();
  return (
    <View style={[styles.frame, { backgroundColor: colors.input }, style]}>
      <View style={[styles.accent, { backgroundColor: colors.interactive }]} />
      <View style={styles.copy}>{children}</View>
      {trailing}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    margin: 3,
    marginBottom: 6,
    paddingLeft: 9,
    paddingRight: 3,
    paddingVertical: 7,
    borderRadius: 16,
    borderCurve: "continuous",
  },
  accent: { alignSelf: "stretch", width: 3, borderRadius: 2 },
  copy: { flex: 1, minWidth: 0, gap: 1 },
});

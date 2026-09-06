import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { BrandBackdrop } from "@/components/brand-backdrop";
import { usePreferences } from "@/preferences/PreferencesProvider";

const IS_ANDROID = process.env.EXPO_OS === "android";

interface BlockingSheetGateViewProps {
  blocked: boolean;
  /** Whether the gate route itself is the active route. */
  presented: boolean;
  children: ReactNode;
}

export function BlockingSheetGateView({
  blocked,
  presented,
  children,
}: BlockingSheetGateViewProps) {
  const { dark } = usePreferences();
  // iOS presents the gate as a native modal above this backdrop. Android
  // presents it inside the stack, under this view, so once the gate route
  // is active the full-screen route covers the app and the backdrop must
  // yield or it would paint over the gate itself.
  const covered = blocked && !(IS_ANDROID && presented);

  return (
    <View style={styles.root}>
      <View
        accessibilityElementsHidden={covered}
        importantForAccessibility={covered ? "no-hide-descendants" : "auto"}
        style={styles.content}
      >
        {children}
      </View>
      {covered ? (
        <View
          importantForAccessibility="no-hide-descendants"
          style={styles.backdrop}
        >
          <StatusBar style={dark ? "light" : "dark"} />
          <BrandBackdrop />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  content: { flex: 1 },
  backdrop: {
    position: "absolute",
    inset: 0,
    zIndex: 1000,
  },
});

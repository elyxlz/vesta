import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { VestaBrand } from "@/components/VestaBrand";
import { usePreferences } from "@/preferences/PreferencesProvider";

const IS_ANDROID = process.env.EXPO_OS === "android";

interface BlockingSheetGateViewProps {
  blocked: boolean;
  /** Whether the gate route itself is the active route. */
  presented: boolean;
  children: ReactNode;
  estimatedSheetHeight: number;
}

export function BlockingSheetGateView({
  blocked,
  presented,
  children,
  estimatedSheetHeight,
}: BlockingSheetGateViewProps) {
  const insets = useSafeAreaInsets();
  const { colors, dark } = usePreferences();
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
          style={[
            styles.backdrop,
            {
              backgroundColor: colors.background,
              paddingTop: insets.top,
            },
          ]}
        >
          <StatusBar style={dark ? "light" : "dark"} />
          <View
            style={[
              styles.hero,
              {
                paddingBottom: estimatedSheetHeight + insets.bottom,
              },
            ]}
          >
            <VestaBrand />
          </View>
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
  hero: {
    flex: 1,
    minHeight: 220,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
  },
});

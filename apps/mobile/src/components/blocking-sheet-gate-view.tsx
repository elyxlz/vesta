import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { VestaBrand } from "@/components/VestaBrand";
import { usePreferences } from "@/preferences/PreferencesProvider";

interface BlockingSheetGateViewProps {
  blocked: boolean;
  children: ReactNode;
  estimatedSheetHeight: number;
}

export function BlockingSheetGateView({
  blocked,
  children,
  estimatedSheetHeight,
}: BlockingSheetGateViewProps) {
  const insets = useSafeAreaInsets();
  const { colors, dark } = usePreferences();

  return (
    <View style={styles.root}>
      <View
        accessibilityElementsHidden={blocked}
        importantForAccessibility={blocked ? "no-hide-descendants" : "auto"}
        style={styles.content}
      >
        {children}
      </View>
      {blocked ? (
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

import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { VestaBrand } from "@/components/VestaBrand";
import { usePreferences } from "@/preferences/PreferencesProvider";

const ESTIMATED_PRIVACY_SHEET_HEIGHT = 181;

interface PrivacyGateViewProps {
  blocked: boolean;
  children: ReactNode;
}

export function PrivacyGateView({
  blocked,
  children,
}: PrivacyGateViewProps) {
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
                paddingBottom:
                  ESTIMATED_PRIVACY_SHEET_HEIGHT + insets.bottom,
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

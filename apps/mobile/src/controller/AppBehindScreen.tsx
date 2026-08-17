import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import * as SplashScreen from "expo-splash-screen";
import { EmptyState } from "@/components/ui/States";
import { usePreferences } from "@/preferences/PreferencesProvider";

// Shown when the sync socket reports "app_behind": this app is older than the gateway's minimum
// supported client (the /sync hello's min_supported), so it fell below the served version window.
// There is no in-app fix, so it points the user at the store to update the app.
export function AppBehindScreen() {
  const { colors } = usePreferences();
  // This screen replaces the navigation tree that would normally hide the boot splash, so it must
  // hide the splash itself or the user stares at it forever.
  useEffect(() => {
    void SplashScreen.hideAsync().catch(() => undefined);
  }, []);
  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <EmptyState
        title="Update Vesta"
        detail="This app is too old for the gateway. Update Vesta from the App Store to reconnect."
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
});

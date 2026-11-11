import { useEffect } from "react";
import { Linking, StyleSheet, View } from "react-native";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { ANDROID_APP_URL, IOS_APP_URL } from "@vesta/core";
import { EmptyState } from "@/components/ui/States";
import { usePreferences } from "@/preferences/PreferencesProvider";

// Shown when the sync socket reports "app_behind": this app is older than the gateway's minimum
// supported client (the /sync hello's min_supported), so it fell below the served version window.
// There is no in-app fix, so it sends the user to where this platform's app is published.
const UPDATE =
  process.env.EXPO_OS === "ios"
    ? {
        detail: "Update Vesta from the App Store to reconnect.",
        label: "Open the App Store",
        url: IOS_APP_URL,
      }
    : {
        detail: "Download the latest Vesta to reconnect.",
        label: "Download the update",
        url: ANDROID_APP_URL,
      };

export function AppBehindScreen() {
  const { colors, dark } = usePreferences();
  // This screen replaces the navigation tree that would normally hide the boot splash, so it must
  // hide the splash itself or the user stares at it forever.
  useEffect(() => {
    void SplashScreen.hideAsync().catch(() => undefined);
  }, []);
  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <StatusBar style={dark ? "light" : "dark"} />
      <EmptyState
        title="Update Vesta"
        detail={`This app is too old for the gateway. ${UPDATE.detail}`}
        action={{
          label: UPDATE.label,
          onPress: () => void Linking.openURL(UPDATE.url),
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
});

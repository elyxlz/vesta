import { StyleSheet, View } from "react-native";
import { EmptyState } from "@/components/ui/States";
import { usePreferences } from "@/preferences/PreferencesProvider";

// Shown when the sync socket reports an "incompatible" protocol: the gateway speaks a
// version this app cannot. There is no in-app fix, so it asks the user to update.
export function IncompatibleScreen() {
  const { colors } = usePreferences();
  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <EmptyState
        title="Update Vesta"
        detail="This gateway runs a newer version than the app. Update Vesta to reconnect."
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
});

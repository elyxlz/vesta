import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { EmptyState } from "@/components/ui/States";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { triggerGatewayUpdate } from "@vesta/core";

// Shown when the sync socket reports "gateway_behind": this app runs a newer release than the
// gateway. Drifting behind the gateway is fine (the served version window handles it); running
// ahead is not. Unlike AppBehindScreen this recovers with no app restart: the button asks the gateway
// to self-update, and the live socket re-hellos into "open" once the gateway restarts newer (its
// reconnect backoff is the retry cadence), so no explicit reconnect is issued here.
export function GatewayBehindScreen() {
  const { colors } = usePreferences();
  const { api } = useSession();
  const [updating, setUpdating] = useState(false);

  const handleUpdate = () => {
    if (updating) return;
    setUpdating(true);
    void triggerGatewayUpdate(api).then((ok) => {
      if (!ok) setUpdating(false);
    });
  };

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <EmptyState
        title="Update gateway"
        detail="This app is newer than the gateway. Update the gateway to reconnect."
        action={{
          label: updating ? "Updating…" : "Update gateway",
          onPress: handleUpdate,
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
});

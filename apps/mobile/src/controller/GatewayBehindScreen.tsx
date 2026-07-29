import { useState } from "react";
import { Alert, StyleSheet, View } from "react-native";
import { AgentOrb } from "@/components/AgentOrb";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { VestaBrand } from "@/components/VestaBrand";
import { unregisterCurrentMobileDevice } from "@/notifications/PushCoordinator";
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
  const { api, disconnect } = useSession();
  const [updating, setUpdating] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  const handleUpdate = () => {
    setUpdating(true);
    void triggerGatewayUpdate(api).then((ok) => {
      if (!ok) setUpdating(false);
    });
  };

  const confirmDisconnect = () => {
    Alert.alert(
      "Disconnect from gateway?",
      "You can reconnect using your account or tunnel link.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Disconnect",
          style: "destructive",
          onPress: () => {
            setDisconnecting(true);
            void unregisterCurrentMobileDevice(api)
              .catch(() => undefined)
              .then(disconnect)
              .catch(() => setDisconnecting(false));
          },
        },
      ],
    );
  };

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <VestaBrand orb={<AgentOrb status="alive" size={88} />} />
      <View style={styles.message}>
        <Text
          accessibilityRole="header"
          family="heading"
          style={[styles.title, { color: colors.text }]}
        >
          Update gateway
        </Text>
        <Text style={[styles.detail, { color: colors.secondaryText }]}>
          This app is newer than the gateway. Update the gateway to reconnect.
        </Text>
      </View>
      <View style={styles.actions}>
        <Button
          pill
          size="large"
          loading={updating}
          loadingLabel="Updating…"
          disabled={disconnecting}
          onPress={handleUpdate}
        >
          Update gateway
        </Button>
        {/* Never gated on `updating`: vestad answers 200 for an update it had nothing to apply
            (already newest for its channel), so leaving stays reachable after a spent update. */}
        <Button
          pill
          size="large"
          variant="secondary"
          icon="log-out-outline"
          iconColor={colors.danger}
          loading={disconnecting}
          onPress={confirmDisconnect}
        >
          Disconnect gateway
        </Button>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    justifyContent: "center",
    gap: 28,
    paddingHorizontal: 28,
  },
  message: { alignItems: "center", gap: 7 },
  title: {
    fontSize: 25,
    lineHeight: 31,
    fontWeight: "600",
    letterSpacing: -0.5,
  },
  detail: { fontSize: 15, lineHeight: 21, textAlign: "center" },
  actions: { gap: 12 },
});

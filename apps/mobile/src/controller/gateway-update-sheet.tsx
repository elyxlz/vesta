import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { triggerGatewayUpdate } from "@vesta/core";
import { AuthPrimaryButton } from "@/components/auth-primary-button";
import { AuthSheet } from "@/components/auth-sheet";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { unregisterCurrentMobileDevice } from "@/notifications/PushCoordinator";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

// The gateway update is complete when the sync socket reconnects and accepts the app version.
// The socket's reconnect backoff is the retry cadence, so the update action does not reconnect it.
export function GatewayUpdateSheet() {
  const { colors } = usePreferences();
  const { api, disconnect } = useSession();
  const [updating, setUpdating] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false);

  const handleUpdate = () => {
    setUpdating(true);
    void triggerGatewayUpdate(api).then((ok) => {
      if (!ok) setUpdating(false);
    });
  };

  const confirmDisconnect = () => {
    setConfirmingDisconnect(true);
  };

  const performDisconnect = () => {
    setConfirmingDisconnect(false);
    setDisconnecting(true);
    void unregisterCurrentMobileDevice(api)
      .catch(() => undefined)
      .then(disconnect)
      .catch(() => setDisconnecting(false));
  };

  return (
    <AuthSheet gap={20}>
      <View style={styles.copy}>
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
        <AuthPrimaryButton
          loading={updating}
          loadingLabel="Updating…"
          disabled={disconnecting}
          onPress={handleUpdate}
        >
          Update gateway
        </AuthPrimaryButton>
        {/* Keep disconnect available after an update starts. The gateway may return success when
            it is already current, which leaves this sheet open and the connection reachable. */}
        <Button
          pill
          size="large"
          variant="secondary"
          icon="log-out-outline"
          iconColor={colors.danger}
          loading={disconnecting}
          labelStyle={styles.actionLabel}
          onPress={confirmDisconnect}
        >
          Disconnect gateway
        </Button>
      </View>
      <ConfirmDialog
        visible={confirmingDisconnect}
        title="Disconnect from gateway?"
        message="You can reconnect using your account or tunnel link."
        confirmLabel="Disconnect"
        destructive
        onConfirm={performDisconnect}
        onDismiss={() => setConfirmingDisconnect(false)}
      />
    </AuthSheet>
  );
}

const styles = StyleSheet.create({
  copy: { alignItems: "center", gap: 7 },
  title: {
    fontSize: 25,
    lineHeight: 31,
    fontWeight: "600",
    letterSpacing: -0.5,
  },
  detail: { fontSize: 15, lineHeight: 21, textAlign: "center" },
  actions: { gap: 12 },
  actionLabel: { fontSize: 14.5, lineHeight: 18, fontWeight: "600" },
});

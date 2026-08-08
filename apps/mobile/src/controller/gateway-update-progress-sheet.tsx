import { useState } from "react";
import { StyleSheet, View } from "react-native";
import {
  dismissGatewayUpdate,
  gatewayOperationLabel,
  triggerGatewayUpdate,
  type GatewayUpdateOperation,
} from "@vesta/core";
import { AuthPrimaryButton } from "@/components/auth-primary-button";
import { AuthSheet } from "@/components/auth-sheet";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

// The whole app while the gateway updates itself: one screen from the first pre-update backup to the
// restart, morphing through the phases in place. It clears itself when the operation does, which is
// when the app reconnects on the new version.
export function GatewayUpdateProgressSheet({
  operation,
}: {
  operation: GatewayUpdateOperation;
}) {
  const { colors } = usePreferences();
  const { api } = useSession();
  const [retrying, setRetrying] = useState(false);
  const failed = operation.phase === "failed";

  // The flag covers only the request itself; once vestad answers, the operation's phase owns this
  // sheet. A granted retry that kept the flag would leave a second failure's retry stuck.
  const handleRetry = () => {
    setRetrying(true);
    void triggerGatewayUpdate(api).finally(() => {
      setRetrying(false);
    });
  };

  return (
    <AuthSheet gap={20}>
      <View style={styles.copy}>
        <Text
          accessibilityRole="header"
          family="heading"
          style={[styles.title, { color: colors.text }]}
        >
          {failed ? "Update failed" : `Updating to v${operation.targetVersion}`}
        </Text>
        <Text style={[styles.detail, { color: colors.secondaryText }]}>
          {failed
            ? (operation.error ??
              "The update stopped before it finished. Your agents are untouched.")
            : "Your gateway backs up every agent before installing, so this can take a few minutes."}
        </Text>
        {!failed && (
          <Text style={[styles.phase, { color: colors.text }]}>
            {gatewayOperationLabel(operation)}
          </Text>
        )}
      </View>
      {failed && (
        <View style={styles.actions}>
          <AuthPrimaryButton loading={retrying} loadingLabel="Retrying…" onPress={handleRetry}>
            Retry update
          </AuthPrimaryButton>
          <Button
            pill
            size="large"
            variant="secondary"
            labelStyle={styles.actionLabel}
            onPress={() => {
              void dismissGatewayUpdate(api);
            }}
          >
            Dismiss
          </Button>
        </View>
      )}
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
  phase: { fontSize: 15, lineHeight: 21, textAlign: "center" },
  actions: { gap: 12 },
  actionLabel: { fontSize: 14.5, lineHeight: 18, fontWeight: "600" },
});

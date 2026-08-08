import { useState } from "react";
import { StyleSheet, View } from "react-native";
import {
  dismissGatewayUpdate,
  gatewayOperationLabel,
  triggerGatewayUpdate,
  type GatewayOperation,
} from "@vesta/core";
import { AuthPrimaryButton } from "@/components/auth-primary-button";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

// What the page calls the operation it is watching, and what it tells the user to expect. A restart
// names no release and touches nothing, so it says so.
function operationCopy(operation: GatewayOperation): {
  title: string;
  detail: string;
} {
  if (operation.phase === "failed") {
    return {
      title: "Update failed",
      detail:
        operation.error ??
        "The update stopped before it finished. Your agents are untouched.",
    };
  }
  if (operation.kind === "restart") {
    return {
      title: "Restarting the gateway",
      detail:
        "Your agents keep running. The app reconnects on its own once the gateway is back.",
    };
  }
  return {
    title: `Updating to v${operation.targetVersion ?? ""}`,
    detail:
      "Your gateway backs up every agent before installing, so this can take a few minutes.",
  };
}

// Home while the gateway works on itself: one page from the first pre-update backup to the restart,
// morphing through the phases in place. Home is where the operation lives so app settings stay one
// tap away throughout, which is what a user reaches for when an update looks stuck.
export function GatewayUpdateProgress({
  operation,
}: {
  operation: GatewayOperation;
}) {
  const { colors } = usePreferences();
  const { api } = useSession();
  const [retrying, setRetrying] = useState(false);
  const failed = operation.phase === "failed";
  const { title, detail } = operationCopy(operation);

  // The flag covers only the request itself; once vestad answers, the operation's phase owns this
  // page. A granted retry that kept the flag would leave a second failure's retry stuck.
  const handleRetry = () => {
    setRetrying(true);
    void triggerGatewayUpdate(api).finally(() => {
      setRetrying(false);
    });
  };

  return (
    <View style={styles.page}>
      <View style={styles.copy}>
        <Text
          accessibilityRole="header"
          family="heading"
          style={[styles.title, { color: colors.text }]}
        >
          {title}
        </Text>
        <Text style={[styles.detail, { color: colors.secondaryText }]}>
          {detail}
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
    </View>
  );
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 24,
    paddingHorizontal: 28,
  },
  copy: { alignItems: "center", gap: 7 },
  title: {
    fontSize: 25,
    lineHeight: 31,
    fontWeight: "600",
    letterSpacing: -0.5,
  },
  detail: { fontSize: 15, lineHeight: 21, textAlign: "center" },
  phase: { fontSize: 15, lineHeight: 21, textAlign: "center" },
  actions: { alignSelf: "stretch", gap: 12 },
  actionLabel: { fontSize: 14.5, lineHeight: 18, fontWeight: "600" },
});

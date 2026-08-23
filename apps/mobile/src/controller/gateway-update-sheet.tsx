import { useState } from "react";
import { StyleSheet, View } from "react-native";
import {
  dismissGatewayUpdate,
  gatewayOperationLabel,
  triggerGatewayUpdate,
  type GatewayOperation,
} from "@vesta/core";
import { AuthPrimaryButton } from "@/components/auth-primary-button";
import { AuthSheet } from "@/components/auth-sheet";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { LoadingSpinner } from "@/components/loading-spinner";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { unregisterCurrentMobileDevice } from "@/notifications/PushCoordinator";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { useGatewayOperation } from "./gateway-operation-context";

// One sheet over the brand hero for everything the gateway does to itself: the update it needs,
// the operation while it runs, and the moment it lands. The gate keeps it presented throughout.
export function GatewayUpdateSheet() {
  const { operation, updatedTo, restarted } = useGatewayOperation();
  if (operation !== null) return <OperationBody operation={operation} />;
  if (updatedTo !== null || restarted) {
    return (
      <LandingBody
        title={
          updatedTo === null ? "Gateway restarted" : `Updated to v${updatedTo}`
        }
        detail={
          updatedTo === null
            ? "Everything is back and your agents are connected."
            : "Your gateway is running the new version."
        }
      />
    );
  }
  return <UpdateNeededBody />;
}

function SheetCopy({ title, detail }: { title: string; detail: string }) {
  const { colors } = usePreferences();
  return (
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
    </View>
  );
}

function operationCopy(operation: GatewayOperation): {
  title: string;
  detail: string;
} {
  if (operation.phase === "failed") {
    return {
      title: "Update didn’t finish",
      detail:
        operation.error ??
        "Something stopped the update. Your agents are untouched.",
    };
  }
  if (operation.kind === "restart") {
    return {
      title: "Restarting gateway",
      detail: "Your agents keep running. This takes a few seconds.",
    };
  }
  return {
    title: `Updating to v${operation.targetVersion ?? ""}`,
    detail: "Each agent is backed up first, so this can take a few minutes.",
  };
}

function OperationBody({ operation }: { operation: GatewayOperation }) {
  const { colors } = usePreferences();
  const { api } = useSession();
  const [retrying, setRetrying] = useState(false);
  const failed = operation.phase === "failed";
  const { title, detail } = operationCopy(operation);

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
      <SheetCopy title={title} detail={detail} />
      {failed ? (
        <View style={styles.actions}>
          <AuthPrimaryButton
            loading={retrying}
            loadingLabel="Retrying…"
            onPress={handleRetry}
          >
            Try again
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
            Not now
          </Button>
        </View>
      ) : (
        <View
          accessibilityLiveRegion="polite"
          accessibilityRole="progressbar"
          style={styles.status}
        >
          <LoadingSpinner size="small" color={colors.interactive} />
          <Text style={[styles.statusText, { color: colors.tertiaryText }]}>
            {gatewayOperationLabel(operation)}
          </Text>
        </View>
      )}
    </AuthSheet>
  );
}

function LandingBody({ title, detail }: { title: string; detail: string }) {
  return (
    <AuthSheet gap={20}>
      <SheetCopy title={title} detail={detail} />
    </AuthSheet>
  );
}

// The gateway update is complete when the sync socket reconnects and accepts the app version.
// The socket's reconnect backoff is the retry cadence, so the update action does not reconnect it.
function UpdateNeededBody() {
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
      <SheetCopy
        title="Update your gateway"
        detail="This version of the app needs a newer gateway. The update takes a few minutes and keeps your agents as they are."
      />
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
          onPress={() => setConfirmingDisconnect(true)}
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
    textAlign: "center",
  },
  detail: { fontSize: 15, lineHeight: 21, textAlign: "center" },
  status: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    minHeight: 24,
  },
  statusText: { fontSize: 13, lineHeight: 18, fontVariant: ["tabular-nums"] },
  actions: { gap: 12 },
  actionLabel: { fontSize: 14.5, lineHeight: 18, fontWeight: "600" },
});

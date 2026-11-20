import { useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { LoadingSpinner } from "@/components/loading-spinner";
import { Ionicons } from "@expo/vector-icons";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
import { AuthSheet } from "@/components/auth-sheet";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { useToast } from "@/components/native-toast";
import { NativeDeleteRow } from "@/components/NativeDeleteRow";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import {
  recentGatewayId,
  type RecentGateway,
} from "@/storage/recent-gateway-model";
import { radii } from "@/theme/layout";

const CONNECTION_PROGRESS_DELAY_MS = 150;
const CONTENT_TRANSITION_MS = 180;

type ConnectionAttempt =
  | {
      gateway: RecentGateway;
      status: "connecting";
    }
  | {
      gateway: RecentGateway;
      status: "error";
      message: string;
    };

function gatewayName(gateway: RecentGateway): string {
  return new URL(gateway.url).host;
}

export default function RecentGatewaysScreen() {
  const {
    status,
    connection,
    recentGateways,
    connectRecentGateway,
    forgetRecentGateway,
  } = useSession();
  const { showError } = useToast();
  const { colors } = usePreferences();
  const router = useRouter();
  const connectionProgressTimer = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const [connectionAttempt, setConnectionAttempt] =
    useState<ConnectionAttempt | null>(null);
  const [showConnectionState, setShowConnectionState] = useState(false);
  const [pendingForget, setPendingForget] = useState<RecentGateway | null>(
    null,
  );
  const isConnecting = connectionAttempt?.status === "connecting";
  const showsConnectionState =
    showConnectionState && connectionAttempt !== null;
  const currentGatewayId = connection ? recentGatewayId(connection.url) : null;

  useEffect(
    () => () => {
      if (connectionProgressTimer.current) {
        clearTimeout(connectionProgressTimer.current);
      }
    },
    [],
  );

  const connect = async (gateway: RecentGateway, showImmediately = false) => {
    if (isConnecting) return;
    const dismissAfterConnect = status === "connected";
    if (connectionProgressTimer.current) {
      clearTimeout(connectionProgressTimer.current);
      connectionProgressTimer.current = null;
    }

    setConnectionAttempt({ gateway, status: "connecting" });
    if (showImmediately) {
      setShowConnectionState(true);
    } else {
      setShowConnectionState(false);
      connectionProgressTimer.current = setTimeout(() => {
        connectionProgressTimer.current = null;
        setShowConnectionState(true);
      }, CONNECTION_PROGRESS_DELAY_MS);
    }

    try {
      await connectRecentGateway(gateway.id);
      if (dismissAfterConnect) router.dismissTo("/");
    } catch (cause) {
      if (connectionProgressTimer.current) {
        clearTimeout(connectionProgressTimer.current);
        connectionProgressTimer.current = null;
      }
      setConnectionAttempt({
        gateway,
        status: "error",
        message: cause instanceof Error ? cause.message : "Connection failed.",
      });
      setShowConnectionState(true);
    }
  };

  const showRecentGateways = () => {
    setShowConnectionState(false);
    setConnectionAttempt(null);
  };

  const confirmForget = (gateway: RecentGateway) => {
    setPendingForget(gateway);
  };

  const performForget = () => {
    const gateway = pendingForget;
    setPendingForget(null);
    if (!gateway) return;
    void forgetRecentGateway(gateway.id).catch((cause: unknown) =>
      showError(cause, "Could not forget this gateway"),
    );
  };

  return (
    <AuthSheet
      mode={showsConnectionState ? "plain" : "scroll"}
      title={
        showsConnectionState
          ? undefined
          : status === "connected"
            ? "Switch gateway"
            : "Recent gateways"
      }
      hasGrabber
    >
      {showsConnectionState ? (
        <Animated.View
          key={`connection-${connectionAttempt.status}`}
          entering={FadeIn.duration(CONTENT_TRANSITION_MS)}
          exiting={FadeOut.duration(CONTENT_TRANSITION_MS)}
          accessibilityLiveRegion="polite"
          accessibilityRole={
            connectionAttempt.status === "connecting" ? "progressbar" : "alert"
          }
          accessibilityLabel={
            connectionAttempt.status === "connecting"
              ? `Connecting to ${gatewayName(connectionAttempt.gateway)}`
              : `Could not connect to ${gatewayName(connectionAttempt.gateway)}. ${connectionAttempt.message}`
          }
          style={styles.connectionState}
        >
          {connectionAttempt.status === "connecting" ? (
            <LoadingSpinner
              size="large"
              color={colors.interactive}
              style={styles.connectionSpinner}
            />
          ) : (
            <View
              style={[
                styles.connectionStateIcon,
                { backgroundColor: colors.input },
              ]}
            >
              <Ionicons
                name="alert-circle-outline"
                size={32}
                color={colors.text}
              />
            </View>
          )}
          <View style={styles.connectionStateCopy}>
            <Text
              family="heading"
              style={[styles.connectionStateTitle, { color: colors.text }]}
            >
              {connectionAttempt.status === "connecting"
                ? `Connecting to ${gatewayName(connectionAttempt.gateway)}`
                : `Couldn’t connect to ${gatewayName(connectionAttempt.gateway)}`}
            </Text>
            {connectionAttempt.status === "error" ? (
              <Text
                selectable
                style={[
                  styles.connectionStateDetail,
                  { color: colors.secondaryText },
                ]}
              >
                {connectionAttempt.message}
              </Text>
            ) : null}
          </View>
          {connectionAttempt.status === "error" ? (
            <View style={styles.connectionStateActions}>
              <Button
                onPress={() => void connect(connectionAttempt.gateway, true)}
              >
                Retry
              </Button>
              <Button variant="secondary" onPress={showRecentGateways}>
                Back to recent gateways
              </Button>
            </View>
          ) : null}
        </Animated.View>
      ) : (
        <Animated.View
          key="gateway-list"
          entering={FadeIn.duration(CONTENT_TRANSITION_MS)}
          exiting={FadeOut.duration(CONTENT_TRANSITION_MS)}
        >
          {recentGateways === null ? (
            <LoadingSpinner style={styles.loading} color={colors.interactive} />
          ) : recentGateways.length === 0 ? (
            <Text style={[styles.empty, { color: colors.secondaryText }]}>
              No saved gateways.
            </Text>
          ) : (
            <View style={styles.listContent}>
              {recentGateways.map((gateway) => {
                const current = gateway.id === currentGatewayId;
                const row = (
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={
                      current
                        ? `${gatewayName(gateway)}, current gateway`
                        : `Connect to ${gatewayName(gateway)}`
                    }
                    disabled={isConnecting || current}
                    onPress={() => void connect(gateway)}
                    style={({ pressed }) => [
                      styles.gatewayMain,
                      { opacity: pressed ? 0.72 : 1 },
                    ]}
                  >
                    <View style={styles.gatewayEdge} />
                    <Text
                      numberOfLines={1}
                      style={[styles.gatewayName, { color: colors.text }]}
                    >
                      {gatewayName(gateway)}
                    </Text>
                    <View style={styles.gatewayEdge}>
                      <Ionicons
                        name={current ? "checkmark" : "chevron-forward"}
                        size={current ? 20 : 16}
                        color={current ? colors.accent : colors.tertiaryText}
                      />
                    </View>
                  </Pressable>
                );
                const containerStyle = [
                  styles.gateway,
                  { backgroundColor: colors.input },
                ];
                return current ? (
                  <View key={gateway.id} style={containerStyle}>
                    {row}
                  </View>
                ) : (
                  <NativeDeleteRow
                    key={gateway.id}
                    containerStyle={containerStyle}
                    deleteAccessibilityLabel={`Forget ${gatewayName(gateway)}`}
                    dangerColor={colors.danger}
                    disabled={isConnecting}
                    onDelete={() => confirmForget(gateway)}
                  >
                    {row}
                  </NativeDeleteRow>
                );
              })}
            </View>
          )}
        </Animated.View>
      )}
      <ConfirmDialog
        visible={pendingForget !== null}
        title={`Forget ${pendingForget ? gatewayName(pendingForget) : ""}?`}
        message="Its saved connection credentials will be permanently removed from this device."
        confirmLabel="Forget"
        destructive
        onConfirm={performForget}
        onDismiss={() => setPendingForget(null)}
      />
    </AuthSheet>
  );
}

const styles = StyleSheet.create({
  loading: { paddingVertical: 30 },
  empty: { textAlign: "center", paddingVertical: 30, fontSize: 14 },
  connectionState: {
    alignItems: "center",
    gap: 18,
  },
  connectionSpinner: { transform: [{ scale: 0.75 }] },
  connectionStateIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: "center",
    justifyContent: "center",
  },
  connectionStateCopy: {
    alignItems: "center",
    gap: 5,
  },
  connectionStateTitle: {
    fontSize: 19,
    lineHeight: 24,
    fontWeight: "500",
    textAlign: "center",
  },
  connectionStateDetail: {
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
  },
  connectionStateActions: {
    alignSelf: "stretch",
    gap: 10,
    marginTop: 4,
  },
  listContent: { gap: 8 },
  gateway: {
    minHeight: 52,
    borderRadius: radii.card,
    borderCurve: "continuous",
    flexDirection: "row",
    alignItems: "center",
    overflow: "hidden",
  },
  gatewayMain: {
    flex: 1,
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 6,
  },
  // The same width on both sides keeps the name on the card's center line.
  gatewayEdge: { width: 20, alignItems: "flex-end" },
  gatewayName: { flex: 1, fontSize: 17, lineHeight: 22, textAlign: "center" },
});

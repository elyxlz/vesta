import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
import { AuthSheet } from "@/components/auth-sheet";
import { NativeDeleteRow } from "@/components/NativeDeleteRow";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import type { RecentGateway } from "@/storage/recent-gateway-model";
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

export default function RecentGatewaysScreen() {
  return <RecentGatewaysContent />;
}

function gatewayName(gateway: RecentGateway): string {
  return new URL(gateway.url).host;
}

function lastConnectedLabel(timestamp: number): string {
  return new Date(timestamp).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function RecentGatewaysContent() {
  const router = useRouter();
  const {
    recentGateways,
    connectRecentGateway,
    forgetRecentGateway,
    clearRecentGateways,
  } = useSession();
  const { colors } = usePreferences();
  const connectionProgressTimer = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const [connectionAttempt, setConnectionAttempt] =
    useState<ConnectionAttempt | null>(null);
  const [showConnectionState, setShowConnectionState] = useState(false);
  const [error, setError] = useState("");
  const isConnecting = connectionAttempt?.status === "connecting";

  useEffect(
    () => () => {
      if (connectionProgressTimer.current) {
        clearTimeout(connectionProgressTimer.current);
      }
    },
    [],
  );

  const connect = async (
    gateway: RecentGateway,
    showImmediately = false,
  ) => {
    if (isConnecting) return;
    if (connectionProgressTimer.current) {
      clearTimeout(connectionProgressTimer.current);
      connectionProgressTimer.current = null;
    }

    setConnectionAttempt({ gateway, status: "connecting" });
    setError("");
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
    Alert.alert(
      `Forget ${gatewayName(gateway)}?`,
      "Its saved connection credentials will be permanently removed from this device.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Forget",
          style: "destructive",
          onPress: () => {
            setError("");
            void forgetRecentGateway(gateway.id).catch((cause: unknown) =>
              setError(
                cause instanceof Error
                  ? cause.message
                  : "Could not forget this gateway.",
              ),
            );
          },
        },
      ],
    );
  };

  const confirmClear = () => {
    Alert.alert(
      "Clear all recent gateways?",
      "All saved gateway credentials will be permanently removed from this device.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Clear all",
          style: "destructive",
          onPress: () => {
            setError("");
            void clearRecentGateways().catch((cause: unknown) =>
              setError(
                cause instanceof Error
                  ? cause.message
                  : "Could not clear recent gateways.",
              ),
            );
          },
        },
      ],
    );
  };

  return (
    <AuthSheet
      mode="scroll"
      title="Recent gateways"
      onClose={() => router.back()}
      hasGrabber
    >
      {showConnectionState && connectionAttempt ? (
        <Animated.View
          key={`connection-${connectionAttempt.status}`}
          entering={FadeIn.duration(CONTENT_TRANSITION_MS)}
          exiting={FadeOut.duration(CONTENT_TRANSITION_MS)}
          accessibilityLiveRegion="polite"
          accessibilityRole={
            connectionAttempt.status === "connecting"
              ? "progressbar"
              : "alert"
          }
          accessibilityLabel={
            connectionAttempt.status === "connecting"
              ? `Connecting to ${gatewayName(connectionAttempt.gateway)}`
              : `Could not connect to ${gatewayName(connectionAttempt.gateway)}. ${connectionAttempt.message}`
          }
          style={styles.connectionState}
        >
          {connectionAttempt.status === "connecting" ? (
            <ActivityIndicator size="large" color={colors.interactive} />
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
                color={colors.danger}
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
            <Text
              style={[
                styles.connectionStateDetail,
                {
                  color:
                    connectionAttempt.status === "error"
                      ? colors.danger
                      : colors.secondaryText,
                },
              ]}
            >
              {connectionAttempt.status === "connecting"
                ? "Using saved connection…"
                : connectionAttempt.message}
            </Text>
          </View>
          {connectionAttempt.status === "error" ? (
            <View style={styles.connectionStateActions}>
              <Button
                pill
                onPress={() => void connect(connectionAttempt.gateway, true)}
              >
                Retry
              </Button>
              <Button
                pill
                variant="secondary"
                onPress={showRecentGateways}
              >
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
            <ActivityIndicator
              style={styles.loading}
              color={colors.interactive}
            />
          ) : recentGateways.length === 0 ? (
            <Text style={[styles.empty, { color: colors.secondaryText }]}>
              No saved gateways.
            </Text>
          ) : (
            <View style={styles.listContent}>
              {recentGateways.map((gateway) => (
                <NativeDeleteRow
                  key={gateway.id}
                  containerStyle={[
                    styles.gateway,
                    {
                      backgroundColor: colors.input,
                      borderColor: colors.border,
                    },
                  ]}
                  deleteAccessibilityLabel={`Forget ${gatewayName(gateway)}`}
                  dangerColor={colors.danger}
                  disabled={isConnecting}
                  onDelete={() => confirmForget(gateway)}
                >
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`Connect to ${gatewayName(gateway)}`}
                    disabled={isConnecting}
                    onPress={() => void connect(gateway)}
                    style={({ pressed }) => [
                      styles.gatewayMain,
                      { opacity: pressed ? 0.72 : 1 },
                    ]}
                  >
                    <View
                      style={[
                        styles.gatewayIcon,
                        { backgroundColor: colors.accentSoft },
                      ]}
                    >
                      <Ionicons
                        name={
                          gateway.hosted ? "cloud-outline" : "server-outline"
                        }
                        size={18}
                        color={colors.text}
                      />
                    </View>
                    <View style={styles.gatewayCopy}>
                      <Text
                        numberOfLines={1}
                        style={[styles.gatewayName, { color: colors.text }]}
                      >
                        {gatewayName(gateway)}
                      </Text>
                      <Text
                        numberOfLines={1}
                        style={[
                          styles.gatewayDetail,
                          { color: colors.secondaryText },
                        ]}
                      >
                        Last connected{" "}
                        {lastConnectedLabel(gateway.lastConnectedAt)}
                      </Text>
                    </View>
                    <Ionicons
                      name="chevron-forward"
                      size={17}
                      color={colors.tertiaryText}
                    />
                  </Pressable>
                </NativeDeleteRow>
              ))}
            </View>
          )}

          {error ? (
            <Text
              accessibilityRole="alert"
              style={[styles.error, { color: colors.danger }]}
            >
              {error}
            </Text>
          ) : null}

          {(recentGateways?.length ?? 0) > 1 ? (
            <View style={styles.clearAction}>
              <Button
                pill
                size="compact"
                variant="ghost"
                icon="trash-outline"
                iconSize={16}
                labelStyle={styles.clearActionLabel}
                disabled={isConnecting}
                onPress={confirmClear}
              >
                Clear all gateways
              </Button>
            </View>
          ) : null}
        </Animated.View>
      )}
    </AuthSheet>
  );
}

const styles = StyleSheet.create({
  loading: { paddingVertical: 30 },
  empty: { textAlign: "center", paddingVertical: 30, fontSize: 14 },
  connectionState: {
    minHeight: 240,
    paddingVertical: 36,
    alignItems: "center",
    justifyContent: "center",
    gap: 18,
  },
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
  listContent: { gap: 10 },
  gateway: {
    minHeight: 64,
    borderRadius: radii.card,
    borderCurve: "continuous",
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: "row",
    alignItems: "center",
    overflow: "hidden",
  },
  gatewayMain: {
    flex: 1,
    minHeight: 64,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 6,
  },
  gatewayIcon: {
    width: 32,
    height: 32,
    borderRadius: 9,
    alignItems: "center",
    justifyContent: "center",
  },
  gatewayCopy: { flex: 1, gap: 2 },
  gatewayName: { fontSize: 16, lineHeight: 20, fontWeight: "500" },
  gatewayDetail: { fontSize: 13, lineHeight: 18 },
  error: {
    marginTop: 16,
    fontSize: 13,
    lineHeight: 18,
    textAlign: "center",
  },
  clearAction: { marginTop: 16 },
  clearActionLabel: { fontSize: 13, lineHeight: 18, fontWeight: "500" },
});

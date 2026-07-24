import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Animated,
  Pressable,
  StyleSheet,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { GatewayCloseButton } from "@/components/GatewayCloseButton";
import { NativeDeleteRow } from "@/components/NativeDeleteRow";
import { Text } from "@/components/ui/Typography";
import {
  ThemeOverrideProvider,
  usePreferences,
} from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import type { RecentGateway } from "@/storage/recent-gateway-model";

export default function RecentGatewaysScreen() {
  return (
    <ThemeOverrideProvider theme="light">
      <RecentGatewaysContent />
    </ThemeOverrideProvider>
  );
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
  const [connectingId, setConnectingId] = useState("");
  const [connectionError, setConnectionError] = useState<{
    gatewayId: string;
    message: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [scrollY] = useState(() => new Animated.Value(0));

  const connect = async (gateway: RecentGateway) => {
    if (connectingId) return;
    setConnectingId(gateway.id);
    setConnectionError(null);
    setError("");
    try {
      await connectRecentGateway(gateway.id);
    } catch (cause) {
      setConnectionError({
        gatewayId: gateway.id,
        message: cause instanceof Error ? cause.message : "Connection failed.",
      });
    } finally {
      setConnectingId("");
    }
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
    <Animated.ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={styles.content}
      contentInsetAdjustmentBehavior="never"
      onScroll={Animated.event(
        [{ nativeEvent: { contentOffset: { y: scrollY } } }],
        { useNativeDriver: true },
      )}
      scrollEventThrottle={16}
      showsVerticalScrollIndicator={false}
      stickyHeaderIndices={[0]}
    >
      <View style={styles.header}>
        <View
          style={[styles.headerSurface, { backgroundColor: colors.background }]}
        >
          <View style={styles.titleRow}>
            <Text
              family="heading"
              style={[styles.title, { color: colors.text }]}
            >
              Recent gateways
            </Text>
            <GatewayCloseButton
              color={colors.text}
              fallbackColor={colors.input}
              onPress={() => router.back()}
            />
          </View>
          <Text style={[styles.subtitle, { color: colors.secondaryText }]}>
            Reconnect to a gateway previously used on this device.
          </Text>
        </View>
        <Animated.View
          pointerEvents="none"
          style={[
            styles.scrollFade,
            {
              opacity: scrollY.interpolate({
                inputRange: [0, 10],
                outputRange: [0, 1],
                extrapolate: "clamp",
              }),
            },
          ]}
        >
          <LinearGradient
            colors={[colors.background, `${colors.background}00`]}
            style={StyleSheet.absoluteFill}
          />
        </Animated.View>
      </View>

      {recentGateways === null ? (
        <ActivityIndicator style={styles.loading} color={colors.interactive} />
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
                  backgroundColor: colors.elevated,
                  borderColor: colors.border,
                },
              ]}
              deleteAccessibilityLabel={`Forget ${gatewayName(gateway)}`}
              dangerColor={colors.danger}
              disabled={Boolean(connectingId)}
              onDelete={() => confirmForget(gateway)}
            >
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Connect to ${gatewayName(gateway)}`}
                disabled={Boolean(connectingId)}
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
                    name={gateway.hosted ? "cloud-outline" : "server-outline"}
                    size={19}
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
                    accessibilityRole={
                      connectionError?.gatewayId === gateway.id
                        ? "alert"
                        : undefined
                    }
                    numberOfLines={1}
                    style={[
                      styles.gatewayDetail,
                      {
                        color:
                          connectionError?.gatewayId === gateway.id
                            ? colors.danger
                            : colors.secondaryText,
                      },
                    ]}
                  >
                    {connectionError?.gatewayId === gateway.id
                      ? connectionError.message
                      : `Last connected ${lastConnectedLabel(gateway.lastConnectedAt)}`}
                  </Text>
                </View>
                {connectingId === gateway.id ? (
                  <ActivityIndicator color={colors.interactive} />
                ) : (
                  <Ionicons
                    name="chevron-forward"
                    size={17}
                    color={colors.tertiaryText}
                  />
                )}
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
        <Pressable
          accessibilityRole="button"
          disabled={Boolean(connectingId)}
          onPress={confirmClear}
          style={({ pressed }) => [
            styles.clear,
            { opacity: pressed ? 0.55 : 1 },
          ]}
        >
          <Text style={[styles.clearText, { color: colors.danger }]}>
            Clear all gateways
          </Text>
        </Pressable>
      ) : null}
    </Animated.ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {
    paddingHorizontal: 24,
    paddingBottom: 24,
  },
  header: { marginHorizontal: -24 },
  headerSurface: {
    gap: 0,
    paddingHorizontal: 24,
    paddingTop: 36,
  },
  scrollFade: { height: 16 },
  titleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
  },
  title: {
    flex: 1,
    fontSize: 28,
    lineHeight: 34,
    fontWeight: "500",
    letterSpacing: -0.7,
  },
  subtitle: { maxWidth: "80%", fontSize: 14, lineHeight: 20 },
  loading: { paddingVertical: 30 },
  empty: { textAlign: "center", paddingVertical: 30, fontSize: 14 },
  listContent: { gap: 10 },
  gateway: {
    minHeight: 64,
    borderRadius: 18,
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
    gap: 11,
    paddingLeft: 12,
    paddingRight: 14,
    paddingVertical: 9,
  },
  gatewayIcon: {
    width: 34,
    height: 34,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  gatewayCopy: { flex: 1, gap: 2 },
  gatewayName: { fontSize: 15, fontWeight: "600" },
  gatewayDetail: { fontSize: 11, lineHeight: 15 },
  error: {
    marginTop: 16,
    fontSize: 13,
    lineHeight: 18,
    textAlign: "center",
  },
  clear: {
    minHeight: 40,
    marginTop: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  clearText: { fontSize: 14, fontWeight: "500" },
});

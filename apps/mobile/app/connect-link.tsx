import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { GatewayCloseButton } from "@/components/GatewayCloseButton";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Form";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

const SCANNED_LINK_LOADING_MS = 1_000;

export default function ConnectLinkScreen() {
  const parameters = useLocalSearchParams<ConnectLinkParameters>();
  const parameterLink = firstParameter(parameters.link) ?? "";
  const parameterAutoConnect =
    firstParameter(parameters.autoConnect) === "true";
  const parameterScanId = firstParameter(parameters.scanId) ?? "";

  return (
    <ConnectLinkContent
      key={`${parameterScanId}:${parameterLink}`}
      initialLink={parameterLink}
      autoConnect={parameterAutoConnect}
      scanId={parameterScanId}
    />
  );
}

type ConnectLinkParameters = {
  link?: string | string[];
  autoConnect?: string | string[];
  scanId?: string | string[];
};

function firstParameter(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function ConnectLinkContent({
  initialLink,
  autoConnect,
  scanId,
}: {
  initialLink: string;
  autoConnect: boolean;
  scanId: string;
}) {
  const router = useRouter();
  const { connectLink } = useSession();
  const { colors, dark } = usePreferences();
  const handledScan = useRef("");
  const [link, setLink] = useState(initialLink);
  const [busy, setBusy] = useState(false);
  const [autoConnecting, setAutoConnecting] = useState(false);
  const [linkVisible, setLinkVisible] = useState(false);
  const [error, setError] = useState("");

  const connect = useCallback(
    async (connectionLink: string, automatic = false) => {
      if (busy) return;
      setBusy(true);
      setAutoConnecting(automatic);
      setError("");
      try {
        if (automatic) {
          await new Promise((resolve) =>
            setTimeout(resolve, SCANNED_LINK_LOADING_MS),
          );
        }
        await connectLink(connectionLink);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Connection failed.");
        setBusy(false);
        setAutoConnecting(false);
      }
    },
    [busy, connectLink],
  );

  useEffect(() => {
    if (!autoConnect || !initialLink) return;
    const attempt = `${scanId}:${initialLink}`;
    if (handledScan.current === attempt) return;
    const timeout = setTimeout(() => {
      handledScan.current = attempt;
      void connect(initialLink, true);
    }, 0);
    return () => clearTimeout(timeout);
  }, [autoConnect, connect, initialLink, scanId]);

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={[styles.sheet, { backgroundColor: colors.card }]}
    >
      <View style={styles.header}>
        <View style={styles.titleRow}>
          <GatewayCloseButton
            color={colors.text}
            fallbackColor={colors.input}
            onPress={() => router.back()}
          />
          <Text family="heading" style={[styles.title, { color: colors.text }]}>
            Connect your gateway
          </Text>
        </View>
        <Text style={[styles.subtitle, { color: colors.secondaryText }]}>
          Enter the connection link provided by your Vesta gateway.
        </Text>
      </View>

      {autoConnecting ? (
        <View
          accessibilityRole="progressbar"
          accessibilityLabel="Connecting to gateway"
          style={styles.connecting}
        >
          <ActivityIndicator color={colors.interactive} />
          <View style={styles.connectingCopy}>
            <Text
              family="heading"
              style={[styles.connectingTitle, { color: colors.text }]}
            >
              Connecting to gateway
            </Text>
            <Text
              style={[styles.connectingDetail, { color: colors.secondaryText }]}
            >
              Verifying the scanned connection link…
            </Text>
          </View>
        </View>
      ) : (
        <View style={styles.form}>
          <Field
            placeholder="Paste your connection link"
            value={link}
            onChangeText={(value) => {
              setLink(value);
              setError("");
            }}
            autoCapitalize="none"
            autoComplete={
              Platform.OS === "android" ? "current-password" : undefined
            }
            autoCorrect={false}
            importantForAutofill={
              Platform.OS === "android" ? "yes" : undefined
            }
            keyboardAppearance={dark ? "dark" : "light"}
            secureTextEntry={!linkVisible}
            textContentType={Platform.OS === "ios" ? "password" : undefined}
            accessory={
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={
                  linkVisible ? "Hide connection link" : "Show connection link"
                }
                hitSlop={8}
                onPress={() => setLinkVisible((visible) => !visible)}
                style={({ pressed }) => [
                  styles.visibilityButton,
                  { opacity: pressed ? 0.55 : 1 },
                ]}
              >
                <Ionicons
                  name={linkVisible ? "eye-off-outline" : "eye-outline"}
                  size={20}
                  color={colors.secondaryText}
                />
              </Pressable>
            }
            error={error || undefined}
          />

          <View style={styles.actions}>
            <View style={styles.connectAction}>
              <Button
                pill
                loading={busy}
                disabled={!link.trim()}
                onPress={() => void connect(link)}
              >
                Connect
              </Button>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Scan connection QR code"
              onPress={() => router.push("/scan")}
              style={({ pressed }) => [
                styles.scanButton,
                { backgroundColor: colors.input, opacity: pressed ? 0.72 : 1 },
              ]}
            >
              <Ionicons name="qr-code-outline" size={21} color={colors.text} />
            </Pressable>
          </View>
        </View>
      )}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  sheet: {
    padding: 24,
    paddingTop: 36,
  },
  header: {
    gap: 0,
  },
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
  connecting: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    marginTop: 16,
    paddingVertical: 12,
  },
  connectingCopy: { flex: 1, gap: 3 },
  connectingTitle: { fontSize: 16, fontWeight: "500" },
  connectingDetail: { fontSize: 14, lineHeight: 20 },
  form: { gap: 16, marginTop: 16 },
  actions: { flexDirection: "row", alignItems: "center", gap: 12 },
  connectAction: { flex: 1 },
  scanButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: "center",
    justifyContent: "center",
  },
  visibilityButton: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
});

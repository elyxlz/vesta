import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { AuthSheet } from "@/components/auth-sheet";
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
    <AuthSheet
      mode="keyboard"
      title="Connect your gateway"
      onClose={() => router.back()}
      hasGrabber
    >
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
              style={[
                styles.connectingDetail,
                { color: colors.secondaryText },
              ]}
            >
              Verifying the scanned connection link…
            </Text>
          </View>
        </View>
      ) : (
        <View style={styles.form}>
          <Field
            accessibilityLabel="Connection link"
            placeholder="Paste your connection link"
            value={link}
            onChangeText={(value) => {
              setLink(value);
              setError("");
            }}
            autoCapitalize="none"
            autoComplete="off"
            autoCorrect={false}
            enablesReturnKeyAutomatically
            importantForAutofill="no"
            keyboardAppearance={dark ? "dark" : "light"}
            onSubmitEditing={() => {
              const connectionLink = link.trim();
              if (connectionLink && !busy) void connect(connectionLink);
            }}
            returnKeyType="go"
            secureTextEntry={!linkVisible}
            textContentType="none"
            accessoryWidth={80}
            accessory={link ? (
              <View style={styles.fieldAccessories}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Clear connection link"
                  hitSlop={4}
                  onPress={() => {
                    setLink("");
                    setLinkVisible(false);
                    setError("");
                  }}
                  style={({ pressed }) => [
                    styles.fieldAccessoryButton,
                    { opacity: pressed ? 0.55 : 1 },
                  ]}
                >
                  <Ionicons
                    name="close-circle"
                    size={19}
                    color={colors.secondaryText}
                  />
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={
                    linkVisible
                      ? "Hide connection link"
                      : "Show connection link"
                  }
                  hitSlop={4}
                  onPress={() => setLinkVisible((visible) => !visible)}
                  style={({ pressed }) => [
                    styles.fieldAccessoryButton,
                    { opacity: pressed ? 0.55 : 1 },
                  ]}
                >
                  <Ionicons
                    name={linkVisible ? "eye-off-outline" : "eye-outline"}
                    size={20}
                    color={colors.secondaryText}
                  />
                </Pressable>
              </View>
            ) : undefined}
            error={error || undefined}
          />

          <View style={styles.actions}>
            <View style={styles.connectAction}>
              <Button
                pill
                loading={busy}
                loadingLabel="Connecting…"
                disabled={!link.trim()}
                onPress={() => void connect(link.trim())}
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
                {
                  backgroundColor: colors.input,
                  opacity: pressed ? 0.72 : 1,
                },
              ]}
            >
              <Ionicons
                name="qr-code-outline"
                size={21}
                color={colors.text}
              />
            </Pressable>
          </View>
        </View>
      )}
    </AuthSheet>
  );
}

const styles = StyleSheet.create({
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
  fieldAccessories: {
    flexDirection: "row",
    alignItems: "center",
  },
  fieldAccessoryButton: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
});

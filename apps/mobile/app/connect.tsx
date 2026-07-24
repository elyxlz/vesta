import { useEffect, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AgentOrb } from "@/components/AgentOrb";
import { BootTransitionTarget } from "@/components/BootTransition";
import { Button, TextButton } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import {
  ThemeOverrideProvider,
  usePreferences,
} from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

export default function ConnectScreen() {
  return (
    <ThemeOverrideProvider theme="light">
      <ConnectContent />
    </ThemeOverrideProvider>
  );
}

function ConnectContent() {
  const insets = useSafeAreaInsets();
  const parameters = useLocalSearchParams<{ link?: string | string[] }>();
  const parameterLink = Array.isArray(parameters.link)
    ? parameters.link[0]
    : parameters.link;
  const initialLink =
    typeof parameterLink === "string" && parameterLink.startsWith("https://")
      ? parameterLink
      : "";
  const router = useRouter();
  const { signIn } = useSession();
  const { colors } = usePreferences();
  const initialDrawerOpened = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!initialLink || initialDrawerOpened.current) return;
    initialDrawerOpened.current = true;
    router.push({ pathname: "/connect-link", params: { link: initialLink } });
  }, [initialLink, router]);

  const signInWithAccount = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const connected = await signIn();
      if (!connected) setBusy(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Connection failed.");
      setBusy(false);
    }
  };

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <View style={styles.hero}>
        <BootTransitionTarget destination="connect" status="alive">
          <AgentOrb status="alive" size={92} />
        </BootTransitionTarget>
        <View style={styles.heroCopy}>
          <Text family="heading" style={[styles.title, { color: colors.text }]}>
            Vesta
          </Text>
          <Text style={[styles.tagline, { color: colors.secondaryText }]}>
            a guardian angel that gives you back time and helps you achieve your
            goals.
          </Text>
        </View>
      </View>

      <View
        style={[
          styles.actionPanel,
          { paddingBottom: Math.max(insets.bottom, 12) },
        ]}
      >
        <Button
          pill
          icon="person-circle-outline"
          loading={busy}
          onPress={() => void signInWithAccount()}
        >
          Connect with Vesta Cloud
        </Button>
        <TextButton onPress={() => router.push("/connect-link")}>
          Self-hosting? Connect your gateway
        </TextButton>
        {error ? (
          <Text
            accessibilityRole="alert"
            style={[styles.error, { color: colors.danger }]}
          >
            {error}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, paddingHorizontal: 24, paddingTop: 24 },
  hero: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    paddingBottom: 24,
  },
  heroCopy: { alignItems: "center", gap: 4 },
  title: { fontSize: 40, fontWeight: "500", letterSpacing: -1.5 },
  tagline: { maxWidth: 330, textAlign: "center", fontSize: 15, lineHeight: 22 },
  actionPanel: { gap: 10 },
  error: { fontSize: 13, textAlign: "center", fontWeight: "600" },
});

import { useState } from "react";
import { StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { AuthSheet } from "@/components/auth-sheet";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

export default function ConnectActionsScreen() {
  const router = useRouter();
  const { recentGateways, signIn } = useSession();
  const { colors } = usePreferences();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const hasRecentGateways = Boolean(recentGateways?.length);

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
    <AuthSheet gap={14}>
      <Button
        pill
        size="large"
        icon="person-circle-outline"
        iconSize={20}
        labelStyle={[styles.actionLabel, styles.primaryActionLabel]}
        loading={busy}
        loadingLabel="Connecting…"
        onPress={() => void signInWithAccount()}
      >
        Connect with Vesta Cloud
      </Button>
      <Button
        pill
        size="large"
        variant="secondary"
        icon="server-outline"
        labelStyle={styles.actionLabel}
        onPress={() => router.push("/connect-link")}
      >
        Connect to self-hosted Vesta
      </Button>
      {hasRecentGateways ? (
        <Button
          pill
          size="compact"
          variant="ghost"
          icon="time-outline"
          iconSize={16}
          labelStyle={[styles.actionLabel, styles.recentActionLabel]}
          onPress={() => router.push("/recent-gateways")}
        >
          Recent gateways
        </Button>
      ) : null}
      {error ? (
        <Text
          accessibilityRole="alert"
          style={[styles.error, { color: colors.danger }]}
        >
          {error}
        </Text>
      ) : null}
    </AuthSheet>
  );
}

const styles = StyleSheet.create({
  actionLabel: { fontSize: 14, lineHeight: 18, fontWeight: "600" },
  primaryActionLabel: { fontSize: 14.5 },
  recentActionLabel: { fontSize: 13, fontWeight: "500" },
  error: { fontSize: 13, textAlign: "center", fontWeight: "600" },
});

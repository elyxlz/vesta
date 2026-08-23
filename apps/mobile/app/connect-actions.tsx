import { useState } from "react";
import { StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { AuthPrimaryButton } from "@/components/auth-primary-button";
import { AuthSheet } from "@/components/auth-sheet";
import { useToast } from "@/components/native-toast";
import { Button } from "@/components/ui/Button";
import { useSession } from "@/session/SessionProvider";

export default function ConnectActionsScreen() {
  const router = useRouter();
  const { recentGateways, signIn } = useSession();
  const { showError } = useToast();
  const [busy, setBusy] = useState(false);
  const hasRecentGateways = Boolean(recentGateways?.length);

  const signInWithAccount = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const connected = await signIn();
      if (!connected) setBusy(false);
    } catch (cause) {
      showError(cause, "Connection failed");
      setBusy(false);
    }
  };

  return (
    <AuthSheet gap={16}>
      <AuthPrimaryButton
        accessibilityLabel="Connect with Vesta Cloud"
        icon="person-circle-outline"
        iconSize={20}
        loading={busy}
        loadingLabel="Connecting…"
        onPress={() => void signInWithAccount()}
      >
        Connect with Vesta Cloud
      </AuthPrimaryButton>
      <Button
        pill
        size="large"
        variant="secondary"
        accessibilityLabel="Connect to self-hosted Vesta"
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
          accessibilityLabel="Recent gateways"
          icon="time-outline"
          iconSize={16}
          labelStyle={[styles.actionLabel, styles.recentActionLabel]}
          onPress={() => router.push("/recent-gateways")}
        >
          Recent gateways
        </Button>
      ) : null}
    </AuthSheet>
  );
}

const styles = StyleSheet.create({
  actionLabel: { fontSize: 14, lineHeight: 18, fontWeight: "600" },
  recentActionLabel: { fontSize: 13, fontWeight: "500" },
});

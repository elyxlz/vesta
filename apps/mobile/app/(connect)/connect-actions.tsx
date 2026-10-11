import { StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { AuthSheet } from "@/components/auth-sheet";
import { Button } from "@/components/ui/Button";
import { useSession } from "@/session/SessionProvider";

export default function ConnectActionsScreen() {
  const router = useRouter();
  const { recentGateways } = useSession();
  const hasRecentGateways = Boolean(recentGateways?.length);

  return (
    <AuthSheet gap={16}>
      <Button
        accessibilityLabel="Connect to self-hosted Vesta"
        icon="server-outline"
        iconSize={20}
        onPress={() => router.push("/connect-link")}
      >
        Connect to self-hosted Vesta
      </Button>
      {hasRecentGateways ? (
        <Button
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

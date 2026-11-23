import { useRouter } from "expo-router";
import { AuthSheet } from "@/components/auth-sheet";
import { Button } from "@/components/ui/Button";
import { useSession } from "@/session/SessionProvider";

export default function ConnectActionsScreen() {
  const router = useRouter();
  const { recentGateways } = useSession();
  const hasRecentGateways = Boolean(recentGateways?.length);

  return (
    <AuthSheet gap={10}>
      <Button
        accessibilityLabel="Connect to Vesta"
        onPress={() => router.push("/connect-link")}
      >
        Connect to Vesta
      </Button>
      {hasRecentGateways ? (
        <Button
          variant="secondary"
          accessibilityLabel="Recent gateways"
          onPress={() => router.push("/recent-gateways")}
        >
          Recent gateways
        </Button>
      ) : null}
    </AuthSheet>
  );
}

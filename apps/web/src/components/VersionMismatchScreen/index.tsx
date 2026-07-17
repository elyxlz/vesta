import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { Footer } from "@/components/Footer";
import { LogoText } from "@/components/Logo/LogoText";
import { Navbar } from "@/components/Navbar";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/providers/AuthProvider";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty";
import { native } from "@/lib/native";

interface VersionMismatchScreenProps {
  gatewayVersion: string;
}

// Full-screen takeover shown in place of the whole app when the app and gateway
// run different versions. The app is a client of vestad, so it always conforms
// to the gateway's version (up or down); upgrading the gateway itself is a
// separate, deliberate action (the UpdatePill). It renders outside the router
// (so /settings is unreachable), so it carries its own disconnect action for
// the user to bail out otherwise.
export function VersionMismatchScreen({
  gatewayVersion,
}: VersionMismatchScreenProps) {
  const { disconnect } = useAuth();
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset if gateway version changes (e.g. update failed, vestad restarted with old version)
  useEffect(() => {
    setUpdating(false);
  }, [gatewayVersion]);

  const handleUpdateApp = async () => {
    setUpdating(true);
    setError(null);
    try {
      // Converge on the gateway's exact version, up or down (allowDowngrade).
      // Targets that version's release so beta (prerelease) gateways update
      // correctly; releases/latest never resolves a prerelease.
      await native.installAppUpdate(gatewayVersion);
    } catch (err) {
      setError(err instanceof Error ? err.message : "update failed");
      setUpdating(false);
    }
  };

  return (
    <>
      <Navbar center={<LogoText />} trailing={<StatusPill />} />
      <Empty>
        <EmptyHeader className="max-w-lg">
          <EmptyTitle>version mismatch</EmptyTitle>
          <EmptyDescription>
            your app (v{__APP_VERSION__}) and your gateway (v{gatewayVersion})
            don't match.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent className="relative">
          <div className="flex items-center gap-2">
            <Button
              onClick={() => {
                void handleUpdateApp();
              }}
              disabled={updating}
            >
              {updating && <Spinner className="size-4" />}
              update app
            </Button>
            <Button
              variant="destructive"
              size="icon"
              aria-label="disconnect"
              title="disconnect"
              onClick={() => disconnect()}
            >
              <LogOut />
            </Button>
          </div>
          {/* absolute so an error never shifts the buttons or header */}
          {error && (
            <p className="absolute top-full mt-4 w-full text-center text-xs text-destructive">
              {error}
            </p>
          )}
        </EmptyContent>
      </Empty>
      <Footer />
    </>
  );
}

import { useState } from "react";
import { LogOut } from "lucide-react";
import { Footer } from "@/components/Footer";
import { LogoText } from "@/components/Logo/LogoText";
import { Navbar } from "@/components/Navbar";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { triggerGatewayUpdate } from "@vesta/core";
import { httpClient } from "@/api/client";
import { useAuth } from "@/providers/AuthProvider";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty";

// Recoverable takeover shown when this app runs a newer release than the gateway (the /sync
// handshake raised "gateway_behind"). Drifting behind the gateway is fine (the served version
// window handles it); running ahead is not, so the app blocks until the gateway catches up. Unlike
// AppBehindScreen this needs no app restart: the "update gateway" button asks vestad to
// self-update, and the live sync socket re-hellos into "open" on its own once the gateway
// restarts newer (its reconnect backoff is the retry cadence). Impossible in a browser by
// construction: vestad serves this exact bundle, so their versions are always equal.
export function GatewayBehindScreen() {
  const { disconnect } = useAuth();
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpdate = async () => {
    setUpdating(true);
    setError(null);
    if (!(await triggerGatewayUpdate(httpClient))) {
      setError("gateway update request failed");
      setUpdating(false);
    }
  };

  return (
    <>
      <Navbar center={<LogoText />} trailing={<StatusPill />} />
      <Empty>
        <EmptyHeader className="max-w-lg">
          <EmptyTitle>gateway is behind</EmptyTitle>
          <EmptyDescription>
            your app (v{__APP_VERSION__}) is newer than your gateway. update the
            gateway to reconnect.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent className="relative">
          <div className="flex items-center gap-2">
            <Button
              onClick={() => {
                void handleUpdate();
              }}
              disabled={updating}
            >
              {updating && <Spinner className="size-4" />}
              update gateway
            </Button>
            <Button
              variant="outline"
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

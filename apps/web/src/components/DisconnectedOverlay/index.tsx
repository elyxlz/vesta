import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { LogOut } from "lucide-react";
import { getConnection } from "@/lib/connection";
import { useAuth } from "@/providers/AuthProvider";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty";

// How long the gateway must stay unreachable before we surface low-level
// diagnostics (endpoint, last attempt) instead of just the reconnect spinner.
const DIAGNOSTICS_DELAY_MS = 10000;

interface DisconnectedOverlayProps {
  lastAttempt: number | null;
}

export function DisconnectedOverlay({ lastAttempt }: DisconnectedOverlayProps) {
  const { disconnect } = useAuth();
  const [showDiagnostics, setShowDiagnostics] = useState(false);

  useEffect(() => {
    const timer = setTimeout(
      () => setShowDiagnostics(true),
      DIAGNOSTICS_DELAY_MS,
    );
    return () => clearTimeout(timer);
  }, []);

  const endpoint = getConnection()?.url ?? null;

  return (
    <motion.div
      role="alertdialog"
      aria-modal="true"
      aria-label="disconnected from gateway"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="absolute inset-0 z-50 flex items-center justify-center bg-muted/80 backdrop-blur-sm"
    >
      <Empty className="border-none">
        <EmptyHeader>
          <Spinner className="size-6" />
          <EmptyTitle>disconnected from gateway</EmptyTitle>
          <EmptyDescription>attempting to reconnect…</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          {showDiagnostics && (
            <div className="text-xs text-muted-foreground">
              {endpoint && <p>endpoint {endpoint}</p>}
              {lastAttempt !== null && (
                <p>last attempt {new Date(lastAttempt).toLocaleTimeString()}</p>
              )}
            </div>
          )}
          <Button variant="destructive" onClick={() => disconnect()}>
            <LogOut data-icon="inline-start" />
            Disconnect
          </Button>
        </EmptyContent>
      </Empty>
    </motion.div>
  );
}

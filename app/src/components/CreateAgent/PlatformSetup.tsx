import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ProgressBar } from "@/components/ProgressBar";
import { checkPlatform, setupPlatform } from "@/api";
import type { PlatformStatus } from "@/lib/types";

interface PlatformSetupProps {
  onReady: () => void;
  onCancel?: () => void;
}

export function PlatformSetup({ onReady, onCancel }: PlatformSetupProps) {
  const [checking, setChecking] = useState(true);
  const [status, setStatus] = useState<PlatformStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showDetails, setShowDetails] = useState(false);

  const doCheck = async () => {
    setChecking(true);
    try {
      const s = await checkPlatform();
      setStatus(s);
      if (s.ready) {
        onReady();
        return;
      }
    } catch (e: unknown) {
      setError((e as { message?: string })?.message || "check failed");
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    doCheck();
  }, [doCheck]);

  const handleInstall = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await setupPlatform();
      if (result.ready) {
        onReady();
      } else {
        setStatus(result);
      }
    } catch (e: unknown) {
      setError((e as { message?: string })?.message || "setup failed");
    } finally {
      setBusy(false);
    }
  };

  if (checking) {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4">
        <h2 className="text-base font-semibold">checking system</h2>
        <p className="text-xs text-muted-foreground">
          making sure everything is ready...
        </p>
        <ProgressBar />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4">
      <h2 className="text-base font-semibold">setting up</h2>
      <p className="text-xs text-muted-foreground text-center">
        {status?.message || "platform setup required."}
      </p>
      {busy ? (
        <ProgressBar />
      ) : (
        <>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <Button size="sm" onClick={handleInstall}>
            retry
          </Button>
        </>
      )}
      {onCancel && (
        <Button variant="link" size="sm" onClick={onCancel}>
          cancel
        </Button>
      )}
    </div>
  );
}

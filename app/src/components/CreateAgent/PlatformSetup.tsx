import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { ProgressBar } from "@/components/ProgressBar";
import { checkPlatform, setupPlatform } from "@/api";

interface PlatformSetupProps {
  onReady: () => void;
  onCancel?: () => void;
}

export function PlatformSetup({ onReady, onCancel }: PlatformSetupProps) {
  const [checking, setChecking] = useState(true);
  const [status, setStatus] = useState<{
    needs_reboot: boolean;
    wsl_installed: boolean;
    virtualization_enabled: boolean | null;
    ready: boolean;
  } | null>(null);
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

  if (status?.needs_reboot) {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4">
        <h2 className="text-base font-semibold">restart required</h2>
        <p className="text-xs text-muted-foreground text-center">
          restart your computer to finish setup, then reopen vesta.
        </p>
        <Button size="sm" onClick={doCheck}>
          check again
        </Button>
      </div>
    );
  }

  if (status?.virtualization_enabled === false) {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4">
        <h2 className="text-base font-semibold">enable virtualization</h2>
        <div className="text-xs text-muted-foreground text-left flex flex-col gap-1">
          <p>1. Restart your computer</p>
          <p>2. Enter BIOS/UEFI settings</p>
          <p>3. Enable Intel VT-x or AMD-V</p>
          <p>4. Save and restart</p>
        </div>
        <Button size="sm" onClick={doCheck}>
          check again
        </Button>
      </div>
    );
  }

  if (!status?.wsl_installed) {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4">
        <h2 className="text-base font-semibold">setting up windows</h2>
        <p className="text-xs text-muted-foreground text-center">
          WSL2 needs to be installed to run vesta agents.
        </p>
        {busy ? (
          <ProgressBar />
        ) : (
          <Button size="sm" onClick={handleInstall}>
            install WSL2
          </Button>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>
              <p>{error}</p>
              <Collapsible open={showDetails} onOpenChange={setShowDetails}>
                <CollapsibleTrigger asChild>
                  <Button
                    variant="link"
                    size="sm"
                    className="h-auto px-0 text-destructive/70"
                  >
                    {showDetails ? "hide details" : "show details"}
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <p className="text-xs text-muted-foreground break-all">
                    {error}
                  </p>
                </CollapsibleContent>
              </Collapsible>
            </AlertDescription>
          </Alert>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4">
      <h2 className="text-base font-semibold">setting up</h2>
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

import { useEffect, useState } from "react";
import { Footer } from "@/components/Footer";
import { LogoText } from "@/components/Logo/LogoText";
import { Navbar } from "@/components/Navbar";
import { Settings } from "@/components/Settings";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";
import { isTauri } from "@/lib/env";

interface VersionMismatchDialogProps {
  gatewayVersion: string;
  onUpdateGateway: () => void;
}

async function updateApp(gatewayVersion: string) {
  if (!isTauri) {
    window.location.reload();
    return;
  }

  const { detectPlatform } = await import("@/lib/platform");
  if (detectPlatform() === "linux") {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("install_update", { version: gatewayVersion });
    return;
  }

  const { check } = await import("@tauri-apps/plugin-updater");
  const update = await check();
  if (update) {
    await update.downloadAndInstall();
  }
}

export function VersionMismatchDialog({
  gatewayVersion,
  onUpdateGateway,
}: VersionMismatchDialogProps) {
  const appIsOlder = gatewayVersion > __APP_VERSION__;
  const hint = appIsOlder ? "update your app" : "update your gateway";
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset if gateway version changes (e.g. update failed, vestad restarted with old version)
  useEffect(() => {
    setUpdating(false);
  }, [gatewayVersion]);

  const handleUpdateGateway = () => {
    setUpdating(true);
    setError(null);
    onUpdateGateway();
  };

  const handleUpdateApp = async () => {
    setUpdating(true);
    setError(null);
    try {
      await updateApp(gatewayVersion);
    } catch (err) {
      setError(err instanceof Error ? err.message : "update failed");
      setUpdating(false);
    }
  };

  return (
    <>
      <Navbar
        center={<LogoText />}
        trailing={
          <>
            <StatusPill />
            <Settings />
          </>
        }
      />
      <Empty>
        <EmptyHeader>
          <EmptyTitle>version mismatch</EmptyTitle>
          <EmptyDescription>
            app v{__APP_VERSION__}, gateway v{gatewayVersion}
          </EmptyDescription>
        </EmptyHeader>
        <Button
          onClick={appIsOlder ? handleUpdateApp : handleUpdateGateway}
          disabled={updating}
        >
          {updating && <Spinner className="size-4" />}
          {hint}
        </Button>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </Empty>
      <Footer />
    </>
  );
}

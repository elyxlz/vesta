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
import { compareVersions } from "@/lib/version";

interface VersionMismatchDialogProps {
  gatewayVersion: string;
  onUpdateGateway: () => Promise<boolean>;
}

async function updateApp(gatewayVersion: string) {
  if (!isTauri) {
    window.location.reload();
    return;
  }

  // Both paths target the gateway's exact version so beta (prerelease) gateways
  // update correctly: Linux installs that version's .deb/.rpm, macOS/Windows point
  // the Tauri updater at that version's manifest (run_update), instead of the static
  // releases/latest endpoint which never resolves a prerelease.
  const { detectPlatform } = await import("@/lib/platform");
  const { invoke } = await import("@tauri-apps/api/core");
  const command =
    detectPlatform() === "linux" ? "install_update" : "run_update";
  await invoke(command, { version: gatewayVersion });
}

export function VersionMismatchDialog({
  gatewayVersion,
  onUpdateGateway,
}: VersionMismatchDialogProps) {
  const appIsOlder = compareVersions(__APP_VERSION__, gatewayVersion) < 0;
  const hint = appIsOlder ? "update your app" : "update your gateway";
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset if gateway version changes (e.g. update failed, vestad restarted with old version)
  useEffect(() => {
    setUpdating(false);
  }, [gatewayVersion]);

  const handleUpdateGateway = async () => {
    setUpdating(true);
    setError(null);
    const ok = await onUpdateGateway();
    if (!ok) {
      setError("update failed");
      setUpdating(false);
    }
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

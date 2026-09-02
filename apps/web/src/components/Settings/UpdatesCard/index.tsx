import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { MenuSection } from "@/components/ui/menu-section";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { UpdatePill } from "@/components/UpdatePill";
import { useGateway } from "@/providers/GatewayProvider/context";
import { useAppUpdate } from "@/hooks/use-app-update";

// The App Settings home for updates, replacing the navbar pill. One row per updatable component:
// Vesta desktop (the app, desktop only, driven by the manual native updater) and the gateway
// (vestad's own self-update). Nothing here surfaces in the chrome; a mismatch screen forces the
// blocking cases instead.
export function UpdatesCard() {
  const {
    reachable,
    gatewayVersion,
    updateAvailable,
    gatewayOperation,
    checkForUpdate,
  } = useGateway();
  const appUpdate = useAppUpdate();
  const [checking, setChecking] = useState(false);

  const onCheck = async () => {
    setChecking(true);
    try {
      await Promise.all([appUpdate.check(), checkForUpdate()]);
    } finally {
      setChecking(false);
    }
  };

  return (
    <Card size="sm">
      <CardContent className="lowercase">
        <MenuSection
          title="updates"
          trailing={
            <Button
              type="button"
              variant="ghost"
              size="xs"
              className="ml-auto text-sm text-muted-foreground"
              disabled={checking}
              onClick={() => {
                void onCheck();
              }}
            >
              <RefreshCw
                data-icon="inline-start"
                className={`size-3.5 ${checking ? "animate-spin" : ""}`}
              />
              check for updates
            </Button>
          }
        >
          {appUpdate.supported && (
            <UpdateRow label="Vesta desktop" version={__APP_VERSION__}>
              <DesktopAction appUpdate={appUpdate} />
            </UpdateRow>
          )}
          {reachable && (
            <UpdateRow label="Vesta gateway" version={gatewayVersion}>
              {updateAvailable || gatewayOperation !== null ? (
                <UpdatePill />
              ) : (
                <OnLatest />
              )}
            </UpdateRow>
          )}
        </MenuSection>
      </CardContent>
    </Card>
  );
}

function UpdateRow({
  label,
  version,
  children,
}: {
  label: string;
  version: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-3 flex items-center justify-between gap-3 text-base leading-none">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="truncate font-medium text-foreground">{label}</span>
        {version && (
          <span className="text-sm text-muted-foreground">v{version}</span>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function OnLatest() {
  return <span className="text-sm text-muted-foreground">on latest</span>;
}

function DesktopAction({
  appUpdate,
}: {
  appUpdate: ReturnType<typeof useAppUpdate>;
}) {
  const { status, phase, percent, start, relaunch } = appUpdate;

  if (phase === "downloading")
    return (
      <Button size="xs" disabled>
        <Spinner className="size-3" />
        {Math.round(percent)}%
      </Button>
    );
  if (phase === "ready")
    return (
      <Button
        size="xs"
        onClick={() => {
          void relaunch();
        }}
      >
        relaunch to finish
      </Button>
    );
  if (status.available || phase === "error")
    return (
      <Button
        size="xs"
        onClick={() => {
          void start();
        }}
      >
        {phase === "error" ? "retry" : "update"}
      </Button>
    );
  return <OnLatest />;
}

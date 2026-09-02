import { useEffect, useMemo, useState } from "react";
import { Cloud, Server, Trash2 } from "lucide-react";
import { router } from "@/router";
import { getConnection, restoreConnection } from "@/lib/connection";
import { cn } from "@/lib/utils";
import {
  forgetRecentGateway,
  readRecentGateways,
  recentGatewayId,
  type RecentGateway,
} from "@/lib/recent-gateways";
import { useAuth } from "@/providers/AuthProvider/context";
import { useControllerReconnect } from "@/providers/ControllerProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/Dialog";

function gatewayHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function lastConnectedLabel(timestamp: number): string {
  const date = new Date(timestamp);
  const day = date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  const time = date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${day} at ${time}`;
}

function currentGatewayId(): string | null {
  const connection = getConnection();
  if (!connection) return null;
  try {
    return recentGatewayId(connection.url);
  } catch {
    return null;
  }
}

function GatewayRow({
  gateway,
  current,
  action,
  onSwitch,
  onForget,
}: {
  gateway: RecentGateway;
  current: boolean;
  action: "connect" | "switch";
  onSwitch: () => void;
  onForget: () => void;
}) {
  const Icon = gateway.hosted ? Cloud : Server;
  const kind = gateway.hosted ? "vesta.run" : "self-hosted";
  return (
    <li
      className={cn(
        "group flex min-w-0 items-center rounded-xl pr-1.5 transition-colors",
        current ? "bg-accent" : "bg-muted/50 hover:bg-muted",
      )}
    >
      <button
        type="button"
        disabled={current}
        onClick={onSwitch}
        aria-label={
          current ? undefined : `${action} to ${gatewayHost(gateway.url)}`
        }
        className="flex min-w-0 flex-1 items-center gap-3 rounded-xl py-2.5 pl-3 text-left disabled:cursor-default"
      >
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-background text-muted-foreground">
          <Icon className="size-4" />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate text-sm font-medium leading-none">
            {gatewayHost(gateway.url)}
          </span>
          <span className="truncate text-xs leading-none text-muted-foreground">
            {kind} · {lastConnectedLabel(gateway.lastConnectedAt)}
          </span>
        </span>
      </button>
      {current ? (
        <Badge className="mr-0.5 shrink-0">current</Badge>
      ) : (
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={`forget ${gatewayHost(gateway.url)}`}
          onClick={onForget}
          className="shrink-0 text-muted-foreground/60 opacity-0 transition-opacity hover:bg-transparent hover:text-destructive group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100"
        >
          <Trash2 />
        </Button>
      )}
    </li>
  );
}

// Mounted only while the dialog is open, so the list reads once per open and no
// pending confirm survives a close.
function SwitchGatewayBody({ onClose }: { onClose: () => void }) {
  const reconnect = useControllerReconnect();
  const { connected, connectSavedGateway } = useAuth();
  const [gateways, setGateways] = useState<RecentGateway[] | null>(null);
  const [pendingForget, setPendingForget] = useState<RecentGateway | null>(
    null,
  );
  const currentId = useMemo(() => currentGatewayId(), []);

  const others = gateways?.filter((gateway) => gateway.id !== currentId) ?? [];

  useEffect(() => {
    let active = true;
    void readRecentGateways()
      .then((saved) => {
        if (active) setGateways(saved);
      })
      .catch((cause: unknown) => {
        console.warn("could not read saved gateways", cause);
        if (active) setGateways([]);
      });
    return () => {
      active = false;
    };
  }, []);

  // Restore the saved short-lived tokens and let the controller reconnect (the
  // refresh flow revives them if they expired); a gateway whose tokens have
  // fully lapsed lands on the app's reauth screen, same as any dead session.
  const switchTo = (gateway: RecentGateway) => {
    if (connected) {
      restoreConnection(gateway.connection);
      reconnect();
    } else {
      connectSavedGateway(gateway.connection);
    }
    void router.navigate("/");
    onClose();
  };

  const confirmForget = () => {
    const gateway = pendingForget;
    setPendingForget(null);
    if (!gateway) return;
    void forgetRecentGateway(gateway.id)
      .then(setGateways)
      .catch((cause: unknown) =>
        console.warn("could not forget saved gateway", cause),
      );
  };

  if (pendingForget) {
    return (
      <>
        <DialogHeader>
          <DialogTitle>forget {gatewayHost(pendingForget.url)}?</DialogTitle>
          <DialogDescription>
            its saved connection is removed from this device. you can reconnect
            with a connect link later.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setPendingForget(null)}>
            cancel
          </Button>
          <Button variant="destructive" onClick={confirmForget}>
            forget
          </Button>
        </DialogFooter>
      </>
    );
  }

  if (gateways === null) {
    return (
      <>
        <DialogHeader>
          <DialogTitle>
            {connected ? "switch gateway" : "recent gateways"}
          </DialogTitle>
          <DialogDescription>
            reconnect to a gateway you've used before.
          </DialogDescription>
        </DialogHeader>
        <p className="py-8 text-center text-sm text-muted-foreground">
          loading saved gateways...
        </p>
      </>
    );
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {connected ? "switch gateway" : "recent gateways"}
        </DialogTitle>
        <DialogDescription>
          reconnect to a gateway you've used before.
        </DialogDescription>
      </DialogHeader>
      {others.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <span className="flex size-11 items-center justify-center rounded-xl bg-muted text-muted-foreground">
            <Server className="size-5" />
          </span>
          <p className="text-sm font-medium">
            {connected ? "no other gateways yet" : "no saved gateways"}
          </p>
          <p className="max-w-[15rem] text-xs text-muted-foreground">
            connect to another with its connect link and it'll show up here.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {gateways.map((gateway) => (
            <GatewayRow
              key={gateway.id}
              gateway={gateway}
              current={gateway.id === currentId}
              action={connected ? "switch" : "connect"}
              onSwitch={() => switchTo(gateway)}
              onForget={() => setPendingForget(gateway)}
            />
          ))}
        </ul>
      )}
    </>
  );
}

export function SwitchGatewayDialog() {
  const open = useDialogs((s) => s.open.switchGateway);
  const setDialogOpen = useDialogs((s) => s.setOpen);
  const setOpen = (next: boolean) => {
    setDialogOpen("switchGateway", next);
  };
  return (
    <Dialog drawerOnMobile open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[min(60vh,480px)] sm:max-w-md">
        <SwitchGatewayBody onClose={() => setOpen(false)} />
      </DialogContent>
    </Dialog>
  );
}

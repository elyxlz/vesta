import type { ReactNode } from "react";
import { Monitor, Smartphone, Globe, HelpCircle, Circle } from "lucide-react";
import type { DeviceInfo, DeviceKind } from "@vesta/core";
import { Card, CardContent } from "@/components/ui/card";
import { MenuSection } from "@/components/ui/menu-section";
import { useGateway } from "@/providers/GatewayProvider";

function kindIcon(kind: DeviceKind): ReactNode {
  const className = "size-4 shrink-0 text-muted-foreground";
  if (kind === "desktop") return <Monitor className={className} />;
  if (kind === "mobile") return <Smartphone className={className} />;
  if (kind === "web") return <Globe className={className} />;
  return <HelpCircle className={className} />;
}

function lastSeenLabel(lastSeen: string): string {
  const then = new Date(lastSeen).getTime();
  if (Number.isNaN(then)) return "last seen recently";
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return "last seen just now";
  if (mins < 60) return `last seen ${String(mins)}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `last seen ${String(hours)}h ago`;
  const days = Math.floor(hours / 24);
  return `last seen ${String(days)}d ago`;
}

function DeviceRow({ device }: { device: DeviceInfo }) {
  return (
    <div className="flex min-w-0 items-center gap-3 text-sm leading-none">
      {kindIcon(device.kind)}
      <span className="min-w-0 flex-1 truncate font-medium text-foreground">
        {device.descriptor ?? "Unnamed device"}
      </span>
      {device.present ? (
        <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-emerald-500">
          <Circle className="size-2 fill-current" />
          present now
        </span>
      ) : (
        <span className="shrink-0 text-xs text-muted-foreground">
          {lastSeenLabel(device.lastSeen)}
        </span>
      )}
    </div>
  );
}

export function DevicesCard() {
  const { devices } = useGateway();
  if (devices.length === 0) return null;
  return (
    <Card size="sm">
      <CardContent>
        <MenuSection title="devices">
          <div className="mt-2 flex flex-col gap-3">
            {devices.map((device) => (
              <DeviceRow key={device.id} device={device} />
            ))}
          </div>
        </MenuSection>
      </CardContent>
    </Card>
  );
}

import { type ReactNode } from "react";
import { Monitor, Smartphone, Globe, HelpCircle, Circle } from "lucide-react";
import type { DeviceInfo, DeviceKind } from "@vesta/core";
import { Card, CardContent } from "@/components/ui/card";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { MenuSection } from "@/components/ui/menu-section";
import { Switch } from "@/components/ui/switch";
import { useScrollFade } from "@/hooks/use-scroll-fade";
import { deviceIdentity } from "@/lib/device-identity";
import { useGateway } from "@/providers/GatewayProvider";
import { useShareLocation } from "@/stores/use-share-location";
import { contextLine } from "./context-line";

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

// This device's location sharing switch, on by default: the presence reporter reads a geolocation
// fix (in the desktop app through its OS location provider), and the OS permission prompt is the
// real consent. Off reports only the timezone and retracts the position the gateway stored for
// this device, so changing your mind wipes it.
function LocationToggle() {
  const enabled = useShareLocation((s) => s.enabled);
  const setEnabled = useShareLocation((s) => s.setEnabled);

  return (
    <Field orientation="horizontal" className="items-center justify-between">
      <FieldContent>
        <FieldLabel className="text-base">
          share this device&apos;s location
        </FieldLabel>
        <FieldDescription>
          let your agents see where this device is; switching off forgets it
        </FieldDescription>
      </FieldContent>
      <Switch checked={enabled} onCheckedChange={setEnabled} />
    </Field>
  );
}

function DeviceRow({
  device,
  locationFallback,
}: {
  device: DeviceInfo;
  locationFallback?: string;
}) {
  const context = contextLine(device, locationFallback);
  return (
    <div className="flex min-w-0 items-center gap-3 text-base leading-none">
      {kindIcon(device.kind)}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="min-w-0 truncate font-medium text-foreground">
          {device.descriptor ?? "unnamed device"}
        </span>
        {context !== null && (
          <span className="min-w-0 truncate text-sm text-muted-foreground">
            {context}
          </span>
        )}
      </div>
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

function ColumnLabel({ children }: { children: ReactNode }) {
  return (
    <span className="text-[0.7rem] font-medium lowercase tracking-wide text-muted-foreground/60">
      {children}
    </span>
  );
}

export function DevicesCard() {
  const { devices } = useGateway();
  const { ref: othersRef, style: othersFade } = useScrollFade<HTMLDivElement>({
    top: "20px",
    bottom: "20px",
  });
  if (devices.length === 0) return null;
  const selfId = deviceIdentity().id;
  const current = devices.find((device) => device.id === selfId) ?? null;
  // Present devices first, then most recently seen.
  const others = devices
    .filter((device) => device.id !== selfId)
    .sort(
      (a, b) =>
        Number(b.present) - Number(a.present) ||
        new Date(b.lastSeen).getTime() - new Date(a.lastSeen).getTime(),
    );
  return (
    <Card size="sm" className="md:col-span-2">
      <CardContent className="lowercase">
        <MenuSection title="devices">
          <div className="mt-2 flex flex-wrap gap-x-8 gap-y-6">
            <div className="flex min-w-[11rem] flex-1 flex-col gap-3">
              <ColumnLabel>this device</ColumnLabel>
              <div className="rounded-xl bg-accent p-3">
                {current ? (
                  <DeviceRow device={current} locationFallback="no location" />
                ) : (
                  <span className="text-base text-muted-foreground">
                    not registered yet
                  </span>
                )}
              </div>
              <LocationToggle />
            </div>
            <div className="flex min-w-[11rem] flex-1 flex-col gap-3">
              <ColumnLabel>other devices</ColumnLabel>
              {others.length === 0 ? (
                <span className="text-base text-muted-foreground">
                  no other devices
                </span>
              ) : (
                <div
                  ref={othersRef}
                  style={othersFade}
                  className="-mx-1 flex max-h-56 flex-col gap-3 overflow-y-auto overscroll-contain px-1 py-2"
                >
                  {others.map((device) => (
                    <DeviceRow key={device.id} device={device} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </MenuSection>
      </CardContent>
    </Card>
  );
}

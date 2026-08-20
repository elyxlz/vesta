import { useEffect, useState, type ReactNode } from "react";
import { Monitor, Smartphone, Globe, HelpCircle, Circle } from "lucide-react";
import type { DeviceInfo, DeviceKind } from "@vesta/core";
import { fetchGatewaySettings, updateGatewaySettings } from "@/api/gateway";
import { Card, CardContent } from "@/components/ui/card";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { MenuSection } from "@/components/ui/menu-section";
import { Switch } from "@/components/ui/switch";
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

// The gateway's user-context switch: whether devices' zone and position are stored and reported to
// the agents. Read once on mount; the PUT answers with the settings, which is what the switch shows.
function UserContextToggle() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchGatewaySettings()
      .then((settings) => {
        if (!cancelled) setEnabled(settings.user_context);
      })
      .catch(() => {
        /* the switch stays hidden when the fetch fails */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (enabled === null) return null;

  const onChange = async (checked: boolean) => {
    setSaving(true);
    try {
      const settings = await updateGatewaySettings({ user_context: checked });
      setEnabled(settings.user_context);
    } catch (err) {
      console.warn("[settings] failed to set user context:", err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Field
      orientation="horizontal"
      className="mt-3 items-center justify-between"
    >
      <FieldContent>
        <FieldLabel className="text-sm">share device context</FieldLabel>
        <FieldDescription>
          tell your agents each device&apos;s timezone and, when a device shares
          it, its location, so they follow your travel; switching off stops the
          reports and forgets what was stored
        </FieldDescription>
      </FieldContent>
      <Switch
        checked={enabled}
        disabled={saving}
        onCheckedChange={(checked) => {
          void onChange(checked);
        }}
      />
    </Field>
  );
}

// This device's own opt-in to share its precise location, on top of the gateway-wide switch above.
// Turning it on makes this browser (or the desktop app) ask for a geolocation fix, which the OS
// prompts for; off reports only the timezone and retracts any stored position.
function LocationToggle() {
  const enabled = useShareLocation((s) => s.enabled);
  const setEnabled = useShareLocation((s) => s.setEnabled);

  return (
    <Field
      orientation="horizontal"
      className="mt-3 items-center justify-between"
    >
      <FieldContent>
        <FieldLabel className="text-sm">
          share this device&apos;s location
        </FieldLabel>
        <FieldDescription>
          let your agents see where this device is, from its precise location;
          your browser asks permission the first time
        </FieldDescription>
      </FieldContent>
      <Switch checked={enabled} onCheckedChange={setEnabled} />
    </Field>
  );
}

function DeviceRow({ device }: { device: DeviceInfo }) {
  return (
    <div className="flex min-w-0 items-center gap-3 text-sm leading-none">
      {kindIcon(device.kind)}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="min-w-0 truncate font-medium text-foreground">
          {device.descriptor ?? "Unnamed device"}
        </span>
        {contextLine(device) !== null && (
          <span className="min-w-0 truncate text-xs text-muted-foreground">
            {contextLine(device)}
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
          <UserContextToggle />
          <LocationToggle />
        </MenuSection>
      </CardContent>
    </Card>
  );
}

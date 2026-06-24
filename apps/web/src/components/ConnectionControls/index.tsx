import { useState } from "react";
import { apiJson } from "@/api/client";
import { useGateway } from "@/providers/GatewayProvider";
import { Switch } from "@/components/ui/switch";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";

function ConnectionToggle({
  label,
  description,
  checked,
  disabled,
  onCheckedChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  disabled: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <Field
      orientation="horizontal"
      className="mt-3 items-center justify-between"
    >
      <FieldContent>
        <FieldLabel className="text-sm">{label}</FieldLabel>
        <FieldDescription>{description}</FieldDescription>
      </FieldContent>
      <Switch
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
      />
    </Field>
  );
}

// Release-channel + auto-update toggles. Shared by the app settings Connection
// card and the version-mismatch screen (which renders outside the router, so it
// can't reach /settings). Owns the save state; the API + re-check logic lives in
// exactly one place.
export function ConnectionControls() {
  const { reachable, gatewayChannel, gatewayAutoUpdate, checkForUpdate } =
    useGateway();
  const [channelSaving, setChannelSaving] = useState(false);
  const [autoUpdateSaving, setAutoUpdateSaving] = useState(false);

  if (!reachable) return null;

  const onToggleBeta = async (enabled: boolean) => {
    setChannelSaving(true);
    try {
      await apiJson("/settings/channel", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel: enabled ? "beta" : "stable" }),
      });
      await checkForUpdate();
    } catch (err) {
      console.warn("[settings] failed to set release channel:", err);
    } finally {
      setChannelSaving(false);
    }
  };

  const onToggleAutoUpdate = async (enabled: boolean) => {
    setAutoUpdateSaving(true);
    try {
      await apiJson("/settings/auto-update", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_update: enabled }),
      });
      await checkForUpdate();
    } catch (err) {
      console.warn("[settings] failed to set auto-update:", err);
    } finally {
      setAutoUpdateSaving(false);
    }
  };

  return (
    <>
      <ConnectionToggle
        label="beta releases"
        description="receive prereleases first to test them before everyone else; switching off stops future betas (it never downgrades)"
        checked={gatewayChannel === "beta"}
        disabled={channelSaving}
        onCheckedChange={onToggleBeta}
      />
      <ConnectionToggle
        label="automatic updates"
        description="apply new releases automatically in the background; switching off keeps you on the current version until you update manually"
        checked={gatewayAutoUpdate}
        disabled={autoUpdateSaving}
        onCheckedChange={onToggleAutoUpdate}
      />
    </>
  );
}

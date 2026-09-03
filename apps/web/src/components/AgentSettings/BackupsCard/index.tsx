import { useEffect, useState } from "react";
import { DatabaseBackup } from "lucide-react";
import { useResource } from "@vesta/core/react";
import {
  Card,
  CardAction,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { fetchAgentBackupSettings, setAgentBackupSettings } from "@vesta/core";
import { httpClient } from "@/api/client";

// Per-agent automatic-backups toggle. Reads the effective enabled state on mount
// and writes an override on change; the section hides its control on load failure.
export function BackupsCard() {
  const { name } = useSelectedAgent();
  const settings = useResource(name || null, (key) =>
    fetchAgentBackupSettings(httpClient, key),
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (settings.error !== null)
      console.warn(
        "[settings] failed to load automatic backups:",
        settings.error,
      );
  }, [settings.error]);

  const onToggle = async (enabled: boolean) => {
    setSaving(true);
    try {
      settings.set(await setAgentBackupSettings(httpClient, name, enabled));
    } catch (err) {
      console.warn("[settings] failed to set automatic backups:", err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <DatabaseBackup className="size-4 text-muted-foreground" />
          automatic backups
        </CardTitle>
        <CardDescription>
          snapshot this agent on a schedule and before every update, without
          interrupting it.
        </CardDescription>
        <CardAction>
          {settings.data ? (
            <Switch
              checked={settings.data.enabled}
              disabled={saving}
              onCheckedChange={(checked) => {
                void onToggle(checked);
              }}
            />
          ) : (
            <Skeleton className="h-5 w-9" />
          )}
        </CardAction>
      </CardHeader>
    </Card>
  );
}

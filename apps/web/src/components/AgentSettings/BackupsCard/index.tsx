import { useEffect, useState } from "react";
import { DatabaseBackup } from "lucide-react";
import {
  Card,
  CardAction,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchAgentBackupSettings,
  setAgentBackupSettings,
  type AgentBackupSettings,
} from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

// Per-agent automatic-backups toggle. Reads the effective enabled state on mount
// and writes an override on change; the section hides its control on load failure.
export function BackupsCard() {
  const { name } = useSelectedAgent();
  const [settings, setSettings] = useState<AgentBackupSettings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!name) return;
    let ignore = false;
    setSettings(null);
    fetchAgentBackupSettings(name)
      .then((s) => {
        if (!ignore) setSettings(s);
      })
      .catch((err: unknown) => {
        if (!ignore)
          console.warn("[settings] failed to load automatic backups:", err);
      });
    return () => {
      ignore = true;
    };
  }, [name]);

  const onToggle = async (enabled: boolean) => {
    setSaving(true);
    try {
      const updated = await setAgentBackupSettings(name, enabled);
      setSettings(updated);
    } catch (err) {
      console.warn("[settings] failed to set automatic backups:", err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="group-data-[size=sm]/card:text-base">
          <DatabaseBackup className="size-4 text-muted-foreground" />
          automatic backups
        </CardTitle>
        <CardDescription className="group-data-[size=sm]/card:text-sm">
          snapshot this agent on a schedule and before every update, without
          interrupting it.
        </CardDescription>
        <CardAction>
          {settings ? (
            <Switch
              checked={settings.enabled}
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

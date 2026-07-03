import { useEffect, useState } from "react";
import { FolderOpen, HardDrive, Lock, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { getAgentMounts, setAgentMounts, type HostMount } from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { errorMessage } from "@/lib/utils";

// Host filesystem grants: host paths the agent may read (and, if writable, write) inside its
// container. A list with add/remove that PUTs the whole list, mirroring the notification rules
// card's data-flow (plain state + effect, no react-query).
export function HostAccessCard() {
  const { name: agentName } = useSelectedAgent();
  const [mounts, setMounts] = useState<HostMount[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [restartHint, setRestartHint] = useState(false);
  const [saving, setSaving] = useState(false);

  const [hostPath, setHostPath] = useState("");
  const [containerPath, setContainerPath] = useState("");
  const [writable, setWritable] = useState(false);

  useEffect(() => {
    if (!agentName) return;
    let ignore = false;
    setMounts(null);
    setLoadError(null);
    getAgentMounts(agentName)
      .then((m) => {
        if (ignore) return;
        setMounts(m);
      })
      .catch((e: unknown) => {
        if (!ignore)
          setLoadError(errorMessage(e, "failed to load host access"));
      });
    return () => {
      ignore = true;
    };
  }, [agentName]);

  const save = async (next: HostMount[]) => {
    if (!agentName) return;
    setSaving(true);
    setSaveError(null);
    try {
      const result = await setAgentMounts(agentName, next);
      setMounts(result.mounts);
      setRestartHint(result.restartRequired);
    } catch (e) {
      setSaveError(errorMessage(e, "failed to update host access"));
    } finally {
      setSaving(false);
    }
  };

  const addPath = () => {
    const path = hostPath.trim();
    if (!path || !mounts) return;
    const next: HostMount = {
      host_path: path,
      container_path: containerPath.trim() || path,
      writable,
    };
    void save([...mounts, next]).then(() => {
      setHostPath("");
      setContainerPath("");
      setWritable(false);
    });
  };

  const removePath = (index: number) => {
    if (!mounts) return;
    void save(mounts.filter((_, i) => i !== index));
  };

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <HardDrive className="size-4 text-muted-foreground" />
          host access
        </CardTitle>
        <CardDescription className="text-xs">
          host paths {agentName || "the agent"} can reach inside its container.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          {loadError ? (
            <p className="text-xs text-destructive">
              failed to load: {loadError}
            </p>
          ) : mounts === null ? (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 2 }).map((_, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Skeleton className="h-5 w-40 rounded-3xl" />
                  <Skeleton className="h-5 w-14 rounded-3xl" />
                </div>
              ))}
            </div>
          ) : (
            <>
              {mounts.length > 0 ? (
                <div className="flex flex-col gap-2">
                  {mounts.map((mount, index) => (
                    <div
                      key={`${mount.container_path}-${index}`}
                      className="flex items-center gap-2 rounded-md"
                    >
                      <FolderOpen className="size-3.5 shrink-0 text-muted-foreground/60" />
                      <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
                        <span
                          className="truncate text-xs font-medium"
                          title={mount.host_path}
                        >
                          {mount.host_path}
                        </span>
                        {mount.container_path !== mount.host_path ? (
                          <span
                            className="truncate text-[11px] text-muted-foreground"
                            title={mount.container_path}
                          >
                            -&gt; {mount.container_path}
                          </span>
                        ) : null}
                      </div>
                      <Badge variant={mount.writable ? "default" : "secondary"}>
                        {mount.writable ? "read-write" : "read-only"}
                      </Badge>
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        aria-label={`remove ${mount.host_path}`}
                        disabled={saving}
                        onClick={() => removePath(index)}
                      >
                        ✕
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground/60">
                  no host paths granted yet.
                </p>
              )}

              <div className="flex flex-col gap-2 rounded-xl border border-border/60 bg-muted/40 p-3">
                <div className="flex items-center gap-2">
                  <Input
                    value={hostPath}
                    onChange={(e) => setHostPath(e.target.value)}
                    placeholder="/mnt/media"
                    aria-label="host path"
                    className="h-8 flex-1 text-xs"
                  />
                  <Input
                    value={containerPath}
                    onChange={(e) => setContainerPath(e.target.value)}
                    placeholder="container path (optional)"
                    aria-label="container path"
                    className="h-8 flex-1 text-xs"
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Switch
                      size="sm"
                      checked={writable}
                      onCheckedChange={setWritable}
                    />
                    writable
                    {!writable ? (
                      <Lock className="size-3 text-muted-foreground/60" />
                    ) : null}
                  </Label>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!hostPath.trim() || saving}
                    onClick={addPath}
                  >
                    <Plus className="size-4" />
                    add path
                  </Button>
                </div>
              </div>

              {saveError ? (
                <p className="text-xs text-destructive">{saveError}</p>
              ) : restartHint ? (
                <p className="text-xs text-muted-foreground/60">
                  restart {agentName || "the agent"} to apply.
                </p>
              ) : null}
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

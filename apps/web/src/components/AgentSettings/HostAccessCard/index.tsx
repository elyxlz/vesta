import { useEffect, useState } from "react";
import { ChevronRight, FolderOpen, Lock, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import { getAgentMounts, setAgentMounts, type HostMount } from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { errorMessage } from "@/lib/utils";

function folderName(path: string): string {
  const segments = path.split("/").filter(Boolean);
  return segments.length > 0 ? segments[segments.length - 1] : path;
}

// Host filesystem grants, behind progressive disclosure: the hub shows a single "shared folders"
// cell; opening it reveals the full list + add/remove/toggle in a dialog. PUTs the whole list.
export function HostAccessCard() {
  const { name: agentName } = useSelectedAgent();
  const [mounts, setMounts] = useState<HostMount[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [restartHint, setRestartHint] = useState(false);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);

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

  const save = async (next: HostMount[]): Promise<boolean> => {
    if (!agentName) return false;
    setSaving(true);
    setSaveError(null);
    try {
      const result = await setAgentMounts(agentName, next);
      setMounts(result.mounts);
      setRestartHint(result.restartRequired);
      return true;
    } catch (e) {
      setSaveError(errorMessage(e, "failed to update host access"));
      return false;
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
    void save([...mounts, next]).then((ok) => {
      if (ok) {
        setHostPath("");
        setContainerPath("");
        setWritable(false);
      }
    });
  };

  const removePath = (index: number) => {
    if (!mounts) return;
    void save(mounts.filter((_, i) => i !== index));
  };

  const toggleWritable = (index: number, value: boolean) => {
    if (!mounts) return;
    void save(
      mounts.map((m, i) => (i === index ? { ...m, writable: value } : m)),
    );
  };

  const summary =
    mounts === null
      ? "…"
      : mounts.length === 0
        ? "none shared yet"
        : `${mounts.length} folder${mounts.length === 1 ? "" : "s"} shared`;

  return (
    <>
      <Card size="sm">
        <CardContent>
          <ItemGroup>
            <Item
              asChild
              variant="muted"
              size="sm"
              className="cursor-pointer text-left hover:bg-muted/70"
            >
              <button type="button" onClick={() => setOpen(true)}>
                <ItemMedia
                  variant="icon"
                  className="size-9 rounded-[10px] bg-sky-500/12 text-sky-600 dark:text-sky-400"
                >
                  <FolderOpen />
                </ItemMedia>
                <ItemContent className="gap-0.5">
                  <ItemTitle>shared folders</ItemTitle>
                  <ItemDescription className="text-[11px]">
                    {summary}
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <ChevronRight className="size-4 text-muted-foreground/60" />
                </ItemActions>
              </button>
            </Item>
          </ItemGroup>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>shared folders</DialogTitle>
            <DialogDescription>
              folders on this computer {agentName || "vesta"} can open.
            </DialogDescription>
          </DialogHeader>

          <div className="flex min-w-0 flex-col gap-3">
            {loadError ? (
              <p className="text-xs text-destructive">
                failed to load: {loadError}
              </p>
            ) : mounts === null ? (
              <div className="flex flex-col gap-2">
                <Skeleton className="h-12 w-full rounded-2xl" />
                <Skeleton className="h-12 w-full rounded-2xl" />
              </div>
            ) : (
              <>
                {mounts.length > 0 ? (
                  <ItemGroup className="min-w-0">
                    {mounts.map((mount, index) => (
                      <Item
                        key={mount.container_path}
                        variant="muted"
                        size="sm"
                      >
                        <ItemMedia
                          variant="icon"
                          className="size-9 rounded-[10px] bg-sky-500/12 text-sky-600 dark:text-sky-400"
                        >
                          <FolderOpen />
                        </ItemMedia>
                        <ItemContent className="min-w-0 gap-0.5">
                          <ItemTitle>{folderName(mount.host_path)}</ItemTitle>
                          <ItemDescription
                            className="text-[11px]"
                            title={mount.host_path}
                          >
                            {mount.host_path}
                            {mount.container_path !== mount.host_path
                              ? ` · seen at ${mount.container_path}`
                              : ""}
                          </ItemDescription>
                        </ItemContent>
                        <ItemActions>
                          <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                            <Switch
                              size="sm"
                              checked={mount.writable}
                              disabled={saving}
                              aria-label={`allow editing ${folderName(mount.host_path)}`}
                              onCheckedChange={(v) => toggleWritable(index, v)}
                            />
                            can edit
                          </span>
                          <Button
                            size="icon-xs"
                            variant="ghost"
                            aria-label={`remove ${mount.host_path}`}
                            disabled={saving}
                            onClick={() => removePath(index)}
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </ItemActions>
                      </Item>
                    ))}
                  </ItemGroup>
                ) : (
                  <p className="text-xs text-muted-foreground/60">
                    no shared folders yet.
                  </p>
                )}

                <div className="flex flex-col gap-2 rounded-xl bg-muted/40 p-3">
                  <Input
                    value={hostPath}
                    onChange={(e) => setHostPath(e.target.value)}
                    placeholder="/mnt/media"
                    aria-label="folder path on this computer"
                    className="h-8 text-xs"
                  />
                  <Input
                    value={containerPath}
                    onChange={(e) => setContainerPath(e.target.value)}
                    placeholder="where vesta sees it (optional)"
                    aria-label="path inside the container"
                    className="h-8 text-xs"
                  />
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Switch
                        size="sm"
                        checked={writable}
                        onCheckedChange={setWritable}
                        aria-label="allow editing"
                      />
                      can edit
                      {!writable ? (
                        <Lock className="size-3 text-muted-foreground/60" />
                      ) : null}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!hostPath.trim() || saving}
                      onClick={addPath}
                    >
                      <Plus className="size-4" />
                      add folder
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
        </DialogContent>
      </Dialog>
    </>
  );
}

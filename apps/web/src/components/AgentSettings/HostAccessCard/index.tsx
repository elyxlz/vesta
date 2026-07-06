import { useEffect, useState } from "react";
import { FolderOpen, Lock, Plus, Trash2 } from "lucide-react";
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
import {
  getAgentMounts,
  getHostFolderSuggestions,
  setAgentMounts,
  type HostMount,
} from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useRestartPending } from "@/stores/use-restart-pending";
import { errorMessage } from "@/lib/utils";

function folderName(path: string): string {
  const segments = path.split("/").filter(Boolean);
  return segments.length > 0 ? segments[segments.length - 1] : path;
}

// Host filesystem grants: the shared folders are listed inline as cells (with a per-folder
// can-edit toggle); an "add a folder" cell opens a dialog for the add flow (suggestions +
// path). PUTs the whole list on every change.
export function HostAccessCard() {
  const { name: agentName } = useSelectedAgent();
  const markRestartPending = useRestartPending((s) => s.markPending);
  const [mounts, setMounts] = useState<HostMount[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);

  const [hostPath, setHostPath] = useState("");
  const [containerPath, setContainerPath] = useState("");
  const [writable, setWritable] = useState(false);
  const [showContainerPath, setShowContainerPath] = useState(false);
  const [suggestions, setSuggestions] = useState<string[] | null>(null);

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

  // Fetch folder suggestions lazily, the first time the add dialog opens.
  useEffect(() => {
    if (!open || suggestions !== null) return;
    let ignore = false;
    getHostFolderSuggestions()
      .then((f) => {
        if (!ignore) setSuggestions(f);
      })
      .catch(() => {
        if (!ignore) setSuggestions([]);
      });
    return () => {
      ignore = true;
    };
  }, [open, suggestions]);

  const save = async (next: HostMount[]): Promise<boolean> => {
    if (!agentName) return false;
    setSaving(true);
    setSaveError(null);
    try {
      const result = await setAgentMounts(agentName, next);
      setMounts(result.mounts);
      if (result.restartRequired) markRestartPending(agentName, "host-access");
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
        setShowContainerPath(false);
        setOpen(false);
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

  // Suggestions not already shared, and not the one being typed.
  const availableSuggestions = (suggestions ?? []).filter(
    (s) => !(mounts ?? []).some((m) => m.host_path === s) && s !== hostPath,
  );

  return (
    <>
      <Card size="sm">
        <CardContent className="flex flex-col gap-2">
          {loadError ? (
            <p className="px-1 text-xs text-destructive">
              failed to load: {loadError}
            </p>
          ) : mounts === null ? (
            <ItemGroup>
              {Array.from({ length: 2 }).map((_, i) => (
                <Item key={i} variant="muted" size="sm">
                  <ItemMedia
                    variant="icon"
                    className="size-9 rounded-[10px] bg-muted"
                  >
                    <Skeleton className="size-4 rounded" />
                  </ItemMedia>
                  <ItemContent>
                    <Skeleton className="h-3 w-36 rounded" />
                  </ItemContent>
                </Item>
              ))}
            </ItemGroup>
          ) : (
            <>
              <ItemGroup>
                {mounts.map((mount, index) => (
                  <Item key={mount.container_path} variant="muted" size="sm">
                    <ItemMedia
                      variant="icon"
                      className="size-9 rounded-[10px] bg-sky-500/12 text-sky-600 dark:text-sky-400"
                    >
                      <FolderOpen />
                    </ItemMedia>
                    <ItemContent className="min-w-0 gap-0.5">
                      <ItemTitle>{folderName(mount.host_path)}</ItemTitle>
                      <ItemDescription title={mount.host_path}>
                        {mount.host_path}
                        {mount.container_path !== mount.host_path
                          ? ` · seen at ${mount.container_path}`
                          : ""}
                      </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                      <span className="text-[11px] text-muted-foreground">
                        {mount.writable ? "can edit" : "view only"}
                      </span>
                      <Switch
                        size="sm"
                        checked={mount.writable}
                        disabled={saving}
                        aria-label={`allow editing ${folderName(mount.host_path)}`}
                        onCheckedChange={(v) => toggleWritable(index, v)}
                      />
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        className="text-muted-foreground/60 hover:text-foreground"
                        aria-label={`remove ${mount.host_path}`}
                        onClick={() => removePath(index)}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </ItemActions>
                  </Item>
                ))}

                <Item
                  asChild
                  variant="outline"
                  size="sm"
                  className="cursor-pointer border-dashed text-left hover:bg-muted/40"
                >
                  <button type="button" onClick={() => setOpen(true)}>
                    <ItemMedia
                      variant="icon"
                      className="size-9 rounded-[10px] bg-amber-500/12 text-amber-600 dark:text-amber-400"
                    >
                      <Plus />
                    </ItemMedia>
                    <ItemContent className="gap-0.5">
                      <ItemTitle>add a folder</ItemTitle>
                      <ItemDescription>
                        choose a folder to share with {agentName || "the agent"}
                      </ItemDescription>
                    </ItemContent>
                  </button>
                </Item>
              </ItemGroup>

              {saveError ? (
                <p className="px-1 text-xs text-destructive">{saveError}</p>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>add a folder</DialogTitle>
            <DialogDescription>
              choose a folder on this computer for {agentName || "the agent"} to
              open.
            </DialogDescription>
          </DialogHeader>

          <div className="flex min-w-0 flex-col gap-3">
            {availableSuggestions.length > 0 ? (
              <div className="flex flex-col gap-1.5">
                <span className="text-[11px] text-muted-foreground">
                  suggested folders
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {availableSuggestions.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => {
                        setHostPath(s);
                        setContainerPath("");
                      }}
                      className="max-w-full truncate rounded-full bg-muted px-2.5 py-1 text-[11px] text-muted-foreground ring-1 ring-border transition-colors hover:text-foreground"
                      title={s}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <Input
              value={hostPath}
              onChange={(e) => setHostPath(e.target.value)}
              placeholder="/mnt/media"
              aria-label="folder path on this computer"
              className="h-8 text-xs"
            />
            {showContainerPath ? (
              <Input
                value={containerPath}
                onChange={(e) => setContainerPath(e.target.value)}
                placeholder={`where ${agentName || "the agent"} sees it (optional)`}
                aria-label="path inside the container"
                className="h-8 text-xs"
                autoFocus
              />
            ) : (
              <button
                type="button"
                onClick={() => setShowContainerPath(true)}
                className="self-start text-[11px] text-muted-foreground transition-colors hover:text-foreground"
              >
                change where {agentName || "the agent"} sees it
              </button>
            )}

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
                disabled={!hostPath.trim() || saving}
                onClick={addPath}
              >
                <Plus className="size-4" />
                add folder
              </Button>
            </div>

            {saveError ? (
              <p className="text-xs text-destructive">{saveError}</p>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

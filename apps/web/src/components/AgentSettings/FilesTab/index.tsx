import { useEffect, useMemo, useState } from "react";
import { FolderTree } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  fetchFileTree,
  readFile,
  writeFile,
  type FileReadResponse,
  type FileTreeEntry,
} from "@/api/files";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useAppMode } from "@/stores/use-app-mode";
import { DreamsViewer } from "./DreamsViewer";
import { FileTree } from "./FileTree";
import { FileEditor } from "./FileEditor";
import { SimpleView } from "./SimpleView";
import { collectDreamPaths, friendlyLabel, isSimpleAllowed } from "./paths";
import { buildTree } from "./tree";

type SaveStatus =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string };

function statusText(status: SaveStatus, dirty: boolean): string {
  switch (status.kind) {
    case "saving":
      return "saving...";
    case "saved":
      return "saved — restart the agent for changes to take effect";
    case "error":
      return status.message;
    default:
      return dirty ? "unsaved changes" : "";
  }
}

function statusClass(status: SaveStatus): string {
  if (status.kind === "error") return "text-destructive";
  return "text-foreground";
}

function AdvancedSkeleton() {
  return (
    <Card size="sm" className="!py-0 !gap-0 flex flex-1 min-h-0 flex-col">
      <CardHeader className="shrink-0 !flex !flex-row !items-center !gap-2.5 !px-5 !py-2.5 border-b border-border/60 [.border-b]:!pb-2.5">
        <Skeleton className="size-4 rounded-full" />
        <Skeleton className="h-3 w-16" />
      </CardHeader>
      <CardContent className="flex-1 min-h-0 !px-3 !py-3">
        <div className="flex flex-col gap-3">
          {[64, 48, 56, 40, 60, 44, 52].map((width, i) => (
            <div key={i} className="flex items-center gap-2">
              <Skeleton className="size-3 shrink-0 rounded" />
              <Skeleton
                className="h-3 rounded"
                style={{ width: `${width}%` }}
              />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function SkeletonRow({ widthPct = 50 }: { widthPct?: number }) {
  return (
    <div className="flex w-full items-center gap-2.5 px-4 py-3">
      <Skeleton className="size-4 shrink-0 rounded-full" />
      <Skeleton className="h-3 rounded" style={{ width: `${widthPct}%` }} />
    </div>
  );
}

function SimpleSkeleton() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-1">
      <Card size="sm" className="!py-0 !gap-0 flex shrink-0 flex-col">
        <SkeletonRow widthPct={32} />
        <div className="border-t border-border/60">
          <SkeletonRow widthPct={28} />
        </div>
      </Card>
      <Card size="sm" className="!py-0 !gap-0 flex flex-1 min-h-0 flex-col">
        <CardHeader className="shrink-0 !flex !flex-row !items-center !gap-2.5 !px-4 !py-2.5 border-b border-border/60 [.border-b]:!pb-2.5">
          <Skeleton className="size-4 rounded-full" />
          <Skeleton className="h-3 w-12" />
        </CardHeader>
        <CardContent className="flex-1 min-h-0 !px-0 !py-0">
          {[44, 56, 36, 48].map((width, i) => (
            <div key={i} className="border-b border-border/60 last:border-b-0">
              <SkeletonRow widthPct={width} />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

export function FilesTab() {
  const { name: agentName, agent } = useSelectedAgent();
  const isAlive = agent?.status === "alive";

  const [entries, setEntries] = useState<FileTreeEntry[] | null>(null);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [loadedFile, setLoadedFile] = useState<FileReadResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState("");
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const mode = useAppMode((s) => s.mode);
  const [dreamsActive, setDreamsActive] = useState(false);

  useEffect(() => {
    if (mode === "simple" && selectedPath && !isSimpleAllowed(selectedPath)) {
      setSelectedPath(null);
      setLoadedFile(null);
    }
  }, [mode, selectedPath]);

  useEffect(() => {
    if (mode === "advanced") setDreamsActive(false);
  }, [mode]);

  const selectFile = (path: string) => {
    setDreamsActive(false);
    setSelectedPath(path);
  };
  const showDreams = () => {
    setDreamsActive(true);
    setSelectedPath(null);
    setLoadedFile(null);
    setLoadError(null);
    setStatus({ kind: "idle" });
  };

  const dreamPaths = useMemo(
    () => (entries ? collectDreamPaths(entries) : []),
    [entries],
  );

  useEffect(() => {
    if (!agentName || !isAlive) {
      setEntries(null);
      return;
    }
    setTreeError(null);
    fetchFileTree(agentName)
      .then(setEntries)
      .catch((e: Error) => setTreeError(e.message));
  }, [agentName, isAlive]);

  useEffect(() => {
    if (!agentName || !selectedPath) return;
    setLoadedFile(null);
    setLoadError(null);
    setStatus({ kind: "idle" });
    readFile(agentName, selectedPath)
      .then((file) => {
        setLoadedFile(file);
        setEditorContent(file.content);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, [agentName, selectedPath]);

  const root = useMemo(
    () => (mode === "advanced" && entries ? buildTree(entries) : null),
    [entries, mode],
  );

  const headerLabel = (() => {
    if (dreamsActive) return "dreams";
    const path = loadedFile?.path ?? selectedPath;
    if (!path) return "select a file";
    return mode === "simple" ? friendlyLabel(path) : path;
  })();

  const dirty =
    loadedFile !== null &&
    loadedFile.encoding === "utf-8" &&
    editorContent !== loadedFile.content;

  const onSave = async () => {
    if (!agentName || !loadedFile || !dirty || loadedFile.readonly) return;
    setStatus({ kind: "saving" });
    try {
      await writeFile(agentName, loadedFile.path, editorContent);
      setLoadedFile({ ...loadedFile, content: editorContent });
      setStatus({ kind: "saved" });
    } catch (e) {
      setStatus({ kind: "error", message: (e as Error).message });
    }
  };

  if (!isAlive) {
    return (
      <p className="px-2 py-6 text-xs text-muted-foreground">
        agent must be running to view files
      </p>
    );
  }

  return (
    <div className="grid h-[70vh] min-h-0 grid-cols-[280px_minmax(0,1fr)] gap-4">
      <div className="flex min-h-0 flex-col gap-2">
        <div className="flex flex-1 min-h-0 flex-col">
          {treeError ? (
            <p className="px-1 py-2 text-xs text-destructive">
              failed to load: {treeError}
            </p>
          ) : !entries ? (
            mode === "simple" ? (
              <SimpleSkeleton />
            ) : (
              <AdvancedSkeleton />
            )
          ) : mode === "simple" ? (
            <SimpleView
              entries={entries}
              selected={selectedPath}
              dreamsActive={dreamsActive}
              onSelect={selectFile}
              onShowDreams={showDreams}
            />
          ) : root ? (
            <Card
              size="sm"
              className="!py-0 !gap-0 flex flex-1 min-h-0 flex-col"
            >
              <CardHeader className="shrink-0 !flex !flex-row !items-center !gap-2.5 !px-5 !py-2.5 border-b border-border/60 [.border-b]:!pb-2.5">
                <FolderTree className="size-4 text-muted-foreground" />
                <CardTitle className="!text-sm !font-medium">/root</CardTitle>
              </CardHeader>
              <CardContent className="flex-1 min-h-0 overflow-auto !px-2 !py-2">
                <FileTree
                  root={root}
                  selected={selectedPath}
                  onSelect={selectFile}
                />
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      <Card size="sm" className="!py-0 !gap-0 flex min-w-0 flex-col">
        {!dreamsActive && (
          <CardHeader className="shrink-0 items-center !px-5 !py-2.5 border-b border-border/60 [.border-b]:!pb-2.5">
            <CardTitle className="truncate !text-xs !font-normal text-muted-foreground">
              {headerLabel}
            </CardTitle>
            <CardAction className="!row-span-1 !self-center flex items-center gap-2">
              {loadedFile?.readonly && (
                <Badge variant="outline" className="text-[10px]">
                  read-only
                </Badge>
              )}
              {(status.kind !== "idle" || dirty) && (
                <span className={cn("text-[10px]", statusClass(status))}>
                  {statusText(status, dirty)}
                </span>
              )}
              <Button
                size="xs"
                disabled={
                  !dirty ||
                  status.kind === "saving" ||
                  (loadedFile?.readonly ?? false)
                }
                onClick={onSave}
              >
                save
              </Button>
            </CardAction>
          </CardHeader>
        )}

        <CardContent className="flex-1 min-h-0 !px-0">
          {dreamsActive && agentName ? (
            <DreamsViewer agent={agentName} dreamPaths={dreamPaths} />
          ) : loadError ? (
            <div className="flex h-full items-center justify-center bg-muted/40 text-sm text-destructive">
              {loadError}
            </div>
          ) : !selectedPath ? (
            <div className="flex h-full items-center justify-center bg-muted/40 text-sm text-muted-foreground">
              select a file to view or edit
            </div>
          ) : !loadedFile ? (
            <Skeleton className="h-full w-full" />
          ) : (
            <FileEditor
              key={loadedFile.path}
              path={loadedFile.path}
              initialContent={loadedFile.content}
              readonly={loadedFile.readonly}
              encoding={loadedFile.encoding}
              onChange={setEditorContent}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

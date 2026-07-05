import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, FolderTree } from "lucide-react";
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
import { Item, ItemContent, ItemGroup, ItemMedia } from "@/components/ui/item";
import { cn, errorMessage } from "@/lib/utils";
import {
  fetchFileTree,
  readFile,
  writeFile,
  type FileReadResponse,
  type FileTreeEntry,
} from "@/api/files";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useIsMobile } from "@/hooks/use-mobile";
import { useFillHeight } from "@/hooks/use-fill-height";
import { useAppMode } from "@/stores/use-app-mode";
import { useRestartPending } from "@/stores/use-restart-pending";
import { DreamsViewer } from "./DreamsViewer";
import { FileTree } from "./FileTree";
import { FileEditor } from "./FileEditor";
import { SimpleView } from "./SimpleView";
import {
  collectDreamPaths,
  CONSTITUTION_PATH,
  friendlyLabel,
  isSimpleAllowed,
} from "./paths";
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
      return "saved";
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
      <CardHeader className="shrink-0 !flex !flex-row !items-center !gap-2.5 !px-5 !py-2.5">
        <Skeleton className="size-4 rounded-full" />
        <Skeleton className="h-3 w-16" />
      </CardHeader>
      <CardContent className="flex-1 min-h-0 !px-3 !py-3">
        <div className="flex flex-col gap-3">
          {Array.from({ length: 9 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2">
              <Skeleton className="size-3 shrink-0 rounded" />
              <Skeleton className="h-3 flex-1 rounded" />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// A hub cell placeholder, shaped like the Item cells the simple view renders.
function HubRowSkeleton() {
  return (
    <Item variant="muted" size="sm">
      <ItemMedia variant="icon" className="size-9 rounded-[10px] bg-muted">
        <Skeleton className="size-4 rounded" />
      </ItemMedia>
      <ItemContent className="gap-1.5">
        <Skeleton className="h-3.5 w-24 rounded" />
        <Skeleton className="h-3 w-40 max-w-full rounded" />
      </ItemContent>
    </Item>
  );
}

function SkeletonSection({
  label,
  rows,
  className,
}: {
  label: string;
  rows: number;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <p className="px-1 text-[11px] font-medium text-muted-foreground/70">
        {label}
      </p>
      <Card size="sm">
        <CardContent>
          <ItemGroup>
            {Array.from({ length: rows }).map((_, i) => (
              <HubRowSkeleton key={i} />
            ))}
          </ItemGroup>
        </CardContent>
      </Card>
    </div>
  );
}

// Matches SimpleView's bento: mind + shared folders left, skills right; one stacked column on mobile.
function SimpleSkeleton({ agentName }: { agentName?: string }) {
  const name = agentName ?? "the agent";
  return (
    <div className="flex flex-col gap-3 p-1 lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-6">
      <div className="contents lg:flex lg:flex-col lg:gap-6">
        <SkeletonSection label={`who ${name} is`} rows={3} />
        <SkeletonSection
          label="shared folders"
          rows={2}
          className="order-3 lg:order-none"
        />
      </div>
      <div className="contents lg:flex lg:flex-col lg:gap-6">
        <SkeletonSection
          label="abilities"
          rows={3}
          className="order-2 lg:order-none"
        />
      </div>
    </div>
  );
}

// Text-like lines of varying width filling the editor area while a file (or the
// whole tab) loads.
const EDITOR_SKELETON_LINES = [
  82, 64, 90, 48, 73, 88, 40, 67, 95, 56, 78, 44, 84, 61, 70, 50, 86, 38,
];

function FileEditorSkeleton() {
  return (
    <div className="flex h-full flex-col gap-3 overflow-hidden px-4 py-4">
      {EDITOR_SKELETON_LINES.map((width, i) => (
        <Skeleton
          key={i}
          className="h-3.5 shrink-0 rounded"
          style={{ width: `${width}%` }}
        />
      ))}
    </div>
  );
}

// The Tabs container's pb-6 sits below the panel on mobile; reserve it.
const MOBILE_BOTTOM_GAP = 24;

export function FilesTab() {
  const { name: agentName, agent } = useSelectedAgent();
  const isAlive = agent?.status === "alive";
  const isMobile = useIsMobile();
  // Mobile uses a drill-in (tree, then editor): the active panel fills the space
  // down to the viewport bottom.
  const { ref: fillRef, height: fillHeight } = useFillHeight(MOBILE_BOTTOM_GAP);

  const [entries, setEntries] = useState<FileTreeEntry[] | null>(null);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [loadedFile, setLoadedFile] = useState<FileReadResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState("");
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const mode = useAppMode((s) => s.mode);
  const markRestartPending = useRestartPending((s) => s.markPending);
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
  // Mobile drill-in: return from the editor/dreams detail view back to the tree.
  const goBack = () => {
    setSelectedPath(null);
    setLoadedFile(null);
    setLoadError(null);
    setDreamsActive(false);
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
    let cancelled = false;
    readFile(agentName, selectedPath)
      .then((file) => {
        if (cancelled) return;
        setLoadedFile(file);
        setEditorContent(file.content);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setLoadError(e.message);
      });
    return () => {
      cancelled = true;
    };
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
      markRestartPending(agentName);
    } catch (e) {
      setStatus({ kind: "error", message: errorMessage(e, "save failed") });
    }
  };

  if (!isAlive) {
    return (
      <p className="px-2 py-6 text-xs text-muted-foreground">
        agent must be running to view files
      </p>
    );
  }

  const saveControls = (
    <>
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
          !dirty || status.kind === "saving" || (loadedFile?.readonly ?? false)
        }
        onClick={onSave}
      >
        save
      </Button>
    </>
  );

  const treeInner = (
    <div className="flex flex-1 min-h-0 flex-col">
      {treeError ? (
        <p className="px-1 py-2 text-xs text-destructive">
          failed to load: {treeError}
        </p>
      ) : !entries ? (
        mode === "simple" ? (
          <SimpleSkeleton agentName={agentName} />
        ) : (
          <AdvancedSkeleton />
        )
      ) : mode === "simple" ? (
        <SimpleView
          entries={entries}
          selected={selectedPath}
          dreamsActive={dreamsActive}
          agentName={agentName}
          onSelect={selectFile}
          onShowDreams={showDreams}
        />
      ) : root ? (
        <Card size="sm" className="!py-0 !gap-0 flex flex-1 min-h-0 flex-col">
          <CardHeader className="shrink-0 !flex !flex-row !items-center !gap-2.5 !px-5 !py-2.5">
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
  );

  const editorBody = (
    <CardContent className="flex-1 min-h-0 !px-0">
      {!entries && !treeError ? (
        <FileEditorSkeleton />
      ) : dreamsActive && agentName ? (
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
        <FileEditorSkeleton />
      ) : (
        <FileEditor
          key={loadedFile.path}
          initialContent={loadedFile.content}
          readonly={loadedFile.readonly}
          encoding={loadedFile.encoding}
          onChange={setEditorContent}
          placeholder={
            loadedFile.path === CONSTITUTION_PATH
              ? "empty — set principles, boundaries, or facts the agent must always honor"
              : undefined
          }
        />
      )}
    </CardContent>
  );

  // Drill-in layout: a hub, then the editor/dreams detail with a back button,
  // one panel at a time. Used on mobile (any mode) and for the calm simple-mode
  // hub on desktop. Advanced desktop keeps the two-pane tree + editor below.
  const drillIn = isMobile || mode === "simple";
  if (drillIn) {
    const inDetail = dreamsActive || selectedPath !== null;
    const panel = inDetail ? (
      <Card size="sm" className="!py-0 !gap-0 flex flex-1 min-w-0 flex-col">
        <div className="shrink-0 flex items-center gap-2 px-3 py-2.5">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="back to files"
            onClick={goBack}
          >
            <ChevronLeft className="size-5" />
          </Button>
          <span className="flex-1 truncate text-xs text-muted-foreground">
            {headerLabel}
          </span>
          {!dreamsActive && saveControls}
        </div>
        {editorBody}
      </Card>
    ) : (
      treeInner
    );

    // The detail view (editor/dreams) is bounded so it scrolls internally; the
    // hub flows naturally and scrolls with the page. Mobile fills the screen.
    if (isMobile) {
      return (
        <div
          ref={fillRef}
          style={{ height: fillHeight }}
          className={cn(
            "flex min-h-0 flex-col",
            !inDetail && "overflow-y-auto",
          )}
        >
          {panel}
        </div>
      );
    }
    return inDetail ? (
      <div className="mx-auto flex h-[70vh] w-full max-w-2xl min-h-0 flex-col">
        {panel}
      </div>
    ) : (
      <div className="mx-auto w-full max-w-4xl">{panel}</div>
    );
  }

  return (
    <div className="grid h-[70vh] min-h-0 grid-cols-[280px_minmax(0,1fr)] gap-4">
      <div className="flex min-h-0 flex-col gap-2">{treeInner}</div>

      <Card size="sm" className="!py-0 !gap-0 flex min-w-0 flex-col">
        {!dreamsActive && (
          <CardHeader className="shrink-0 items-center !px-5 !py-2.5">
            <CardTitle className="truncate !text-xs !font-normal text-muted-foreground">
              {!entries && !treeError ? (
                <Skeleton className="h-3 w-28" />
              ) : (
                headerLabel
              )}
            </CardTitle>
            <CardAction className="!row-span-1 !self-center flex items-center gap-2">
              {entries ? (
                saveControls
              ) : (
                <Skeleton className="h-6 w-12 rounded-full" />
              )}
            </CardAction>
          </CardHeader>
        )}
        {editorBody}
      </Card>
    </div>
  );
}

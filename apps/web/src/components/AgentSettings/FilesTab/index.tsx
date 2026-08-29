import { useEffect, useMemo, useState } from "react";
import { ChevronLeft } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { useRestartPending } from "@/stores/use-restart-pending";
import { DreamsViewer } from "./DreamsViewer";
import { FileEditor } from "./FileEditor";
import { SimpleView } from "./SimpleView";
import {
  collectDreamPaths,
  CONSTITUTION_PATH,
  friendlyLabel,
  isSimpleAllowed,
} from "./paths";

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
          style={{ width: `${String(width)}%` }}
        />
      ))}
    </div>
  );
}

// Reserve the floating nav pill's height so the filled panel clears it (matches
// the flowing tabs' max-md:pb-28 in AgentSettings).
const MOBILE_BOTTOM_GAP = 112;

function SaveControls({
  loadedFile,
  status,
  dirty,
  onSave,
}: {
  loadedFile: FileReadResponse | null;
  status: SaveStatus;
  dirty: boolean;
  onSave: () => Promise<void>;
}) {
  return (
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
        onClick={() => {
          void onSave();
        }}
      >
        save
      </Button>
    </>
  );
}

function TreePanel({
  entries,
  treeError,
  agentName,
  selectedPath,
  dreamsActive,
  onSelect,
  onShowDreams,
}: {
  entries: FileTreeEntry[] | null;
  treeError: string | null;
  agentName: string;
  selectedPath: string | null;
  dreamsActive: boolean;
  onSelect: (path: string) => void;
  onShowDreams: () => void;
}) {
  return (
    <div className="flex flex-1 min-h-0 flex-col">
      {treeError ? (
        <p className="px-1 py-2 text-xs text-destructive">
          failed to load: {treeError}
        </p>
      ) : !entries ? (
        <SimpleSkeleton agentName={agentName} />
      ) : (
        <SimpleView
          entries={entries}
          selected={selectedPath}
          dreamsActive={dreamsActive}
          agentName={agentName}
          onSelect={onSelect}
          onShowDreams={onShowDreams}
        />
      )}
    </div>
  );
}

function EditorBody({
  entries,
  treeError,
  dreamsActive,
  agentName,
  dreamPaths,
  loadError,
  selectedPath,
  loadedFile,
  onChange,
}: {
  entries: FileTreeEntry[] | null;
  treeError: string | null;
  dreamsActive: boolean;
  agentName: string;
  dreamPaths: string[];
  loadError: string | null;
  selectedPath: string | null;
  loadedFile: FileReadResponse | null;
  onChange: (content: string) => void;
}) {
  return (
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
          onChange={onChange}
          placeholder={
            loadedFile.path === CONSTITUTION_PATH
              ? "empty — set principles, boundaries, or facts the agent must always honor"
              : undefined
          }
        />
      )}
    </CardContent>
  );
}

// Wrapper for the one-panel-at-a-time layout: mobile fills the screen; desktop
// bounds the detail view so it scrolls internally and lets the hub flow.
function DrillInContainer({
  isMobile,
  inDetail,
  fillRef,
  fillHeight,
  children,
}: {
  isMobile: boolean;
  inDetail: boolean;
  fillRef: (node: HTMLDivElement | null) => void;
  fillHeight: number;
  children: React.ReactNode;
}) {
  if (isMobile) {
    // The hub flows with the page scroll like the other tabs (no nested scroll,
    // pb-28 to clear the nav pill); only the detail view fills to the bottom.
    if (!inDetail) {
      return <div className="flex flex-col pb-28">{children}</div>;
    }
    return (
      <div
        ref={fillRef}
        style={{ height: fillHeight }}
        className="flex min-h-0 flex-col"
      >
        {children}
      </div>
    );
  }
  return inDetail ? (
    <div className="mx-auto flex h-[70vh] w-full max-w-2xl min-h-0 flex-col">
      {children}
    </div>
  ) : (
    <div className="mx-auto w-full max-w-4xl">{children}</div>
  );
}

export function FilesTab() {
  const { name: agentName, agent } = useSelectedAgent();
  const isAlive = agent.status === "alive";
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
  const markRestartPending = useRestartPending((s) => s.markPending);
  const [dreamsActive, setDreamsActive] = useState(false);

  useEffect(() => {
    if (selectedPath && !isSimpleAllowed(selectedPath)) {
      setSelectedPath(null);
      setLoadedFile(null);
    }
  }, [selectedPath]);

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
    let cancelled = false;
    fetchFileTree(agentName)
      .then((entries) => {
        if (cancelled) return;
        setEntries(entries);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setTreeError(errorMessage(e, "failed to load files"));
      });
    return () => {
      cancelled = true;
    };
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
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadError(errorMessage(e, "failed to load file"));
      });
    return () => {
      cancelled = true;
    };
  }, [agentName, selectedPath]);

  const headerLabel = (() => {
    if (dreamsActive) return "dreams";
    const path = loadedFile?.path ?? selectedPath;
    if (!path) return "select a file";
    return friendlyLabel(path);
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
      markRestartPending(agentName, "files", agent.startedAt);
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
    <SaveControls
      loadedFile={loadedFile}
      status={status}
      dirty={dirty}
      onSave={onSave}
    />
  );

  const treeInner = (
    <TreePanel
      entries={entries}
      treeError={treeError}
      agentName={agentName}
      selectedPath={selectedPath}
      dreamsActive={dreamsActive}
      onSelect={selectFile}
      onShowDreams={showDreams}
    />
  );

  const editorBody = (
    <EditorBody
      entries={entries}
      treeError={treeError}
      dreamsActive={dreamsActive}
      agentName={agentName}
      dreamPaths={dreamPaths}
      loadError={loadError}
      selectedPath={selectedPath}
      loadedFile={loadedFile}
      onChange={setEditorContent}
    />
  );

  // Drill-in layout: a hub, then the editor/dreams detail with a back button,
  // one panel at a time.
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

  return (
    <DrillInContainer
      isMobile={isMobile}
      inDetail={inDetail}
      fillRef={fillRef}
      fillHeight={fillHeight}
    >
      {panel}
    </DrillInContainer>
  );
}

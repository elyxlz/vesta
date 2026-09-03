import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { DreamsViewer } from "./DreamsViewer";
import type { SaveStatus } from "./use-file-editor";
import { FileEditor } from "./FileEditor";
import { SimpleView } from "./SimpleView";
import { CONSTITUTION_PATH } from "./paths";
import { SimpleSkeleton, FileEditorSkeleton } from "./skeletons";
import type { FileReadResponse, FileTreeEntry } from "@vesta/core";

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

export const MOBILE_BOTTOM_GAP = 112;

export function SaveControls({
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

export function TreePanel({
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

export function EditorBody({
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
              ? "empty. set principles, boundaries, or facts the agent must always honor"
              : undefined
          }
        />
      )}
    </CardContent>
  );
}

// Wrapper for the one-panel-at-a-time layout: mobile fills the screen; desktop
// bounds the detail view so it scrolls internally and lets the hub flow.

// Wrapper for the one-panel-at-a-time layout: mobile fills the screen; desktop
// bounds the detail view so it scrolls internally and lets the hub flow.
export function DrillInContainer({
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

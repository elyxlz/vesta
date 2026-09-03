import { useMemo, useState } from "react";
import { useResource } from "@vesta/core/react";
import { ChevronLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { errorMessage, loadFailure } from "@/lib/utils";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { useIsMobile } from "@/hooks/use-mobile";
import { useFillHeight } from "@/hooks/use-fill-height";
import { useRestartPending } from "@/stores/use-restart-pending";
import { useFileEditor } from "./use-file-editor";
import { collectDreamPaths, friendlyLabel, isSimpleAllowed } from "./paths";
import {
  SaveControls,
  TreePanel,
  EditorBody,
  DrillInContainer,
  MOBILE_BOTTOM_GAP,
} from "./editor-panels";
import { fetchFileTree, writeFile } from "@vesta/core";
import { httpClient } from "@/api/client";

export function FilesTab() {
  const { name: agentName, agent } = useSelectedAgent();
  const isAlive = agent.status === "alive";
  const isMobile = useIsMobile();
  // Mobile uses a drill-in (tree, then editor): the active panel fills the space
  // down to the viewport bottom.
  const { ref: fillRef, height: fillHeight } = useFillHeight(MOBILE_BOTTOM_GAP);

  const tree = useResource(agentName && isAlive ? agentName : null, (key) =>
    fetchFileTree(httpClient, key),
  );
  const entries = tree.data;
  const treeError = loadFailure(tree.error, "failed to load files");
  // The selection only counts while the simple view allows it, so a path the view no longer
  // lists drops out during render.
  const [selection, setSelection] = useState<string | null>(null);
  const selectedPath =
    selection !== null && isSimpleAllowed(selection) ? selection : null;
  const {
    loadedFile,
    loadError,
    editorContent,
    setEditorContent,
    status,
    setStatus,
    setLoadedFile,
  } = useFileEditor(agentName, selectedPath);
  const markRestartPending = useRestartPending((s) => s.markPending);
  const [dreamsActive, setDreamsActive] = useState(false);

  const selectFile = (path: string) => {
    setDreamsActive(false);
    setSelection(path);
  };
  const showDreams = () => {
    setDreamsActive(true);
    setSelection(null);
  };
  // Mobile drill-in: return from the editor/dreams detail view back to the tree.
  const goBack = () => {
    setSelection(null);
    setDreamsActive(false);
  };

  const dreamPaths = useMemo(
    () => (entries ? collectDreamPaths(entries) : []),
    [entries],
  );

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
      await writeFile(httpClient, agentName, loadedFile.path, editorContent);
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

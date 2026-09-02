import { useState } from "react";
import { useResource } from "@vesta/core/react";
import { loadFailure } from "@/lib/utils";
import { readFile } from "@vesta/core";
import type { FileReadResponse } from "@vesta/core";
import { httpClient } from "@/api/client";

export type SaveStatus =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string };

// The editor's file, its edit, and its save status, each keyed to the selection, so a new
// selection shows fresh state instead of resetting the old one from an effect.
export function useFileEditor(agentName: string, selectedPath: string | null) {
  const file = useResource(
    agentName && selectedPath ? `${agentName}\n${selectedPath}` : null,
    (key) => readFile(httpClient, agentName, key.slice(agentName.length + 1)),
  );
  const loadedFile = file.data;
  const loadError = loadFailure(file.error, "failed to load file");
  // The editor's text is an edit of one loaded file; a newly loaded file shows its own content.
  const [edit, setEdit] = useState<{
    file: FileReadResponse;
    content: string;
  } | null>(null);
  const editorContent =
    edit !== null && edit.file === loadedFile
      ? edit.content
      : (loadedFile?.content ?? "");
  const setEditorContent = (content: string) => {
    if (loadedFile !== null) setEdit({ file: loadedFile, content });
  };
  // Save status belongs to the file it reports on.
  const [statusFor, setStatusFor] = useState<{
    path: string | null;
    status: SaveStatus;
  }>({ path: null, status: { kind: "idle" } });
  const status: SaveStatus =
    statusFor.path === selectedPath ? statusFor.status : { kind: "idle" };
  const setStatus = (next: SaveStatus) => {
    setStatusFor({ path: selectedPath, status: next });
  };
  return {
    loadedFile,
    loadError,
    editorContent,
    setEditorContent,
    status,
    setStatus,
    setLoadedFile: file.set,
  };
}

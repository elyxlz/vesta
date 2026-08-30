import { useState, type DragEvent } from "react";
import {
  carriesFiles,
  dragEnded,
  dragEntered,
  dragLeft,
  isDragActive,
} from "./drop-zone-model";

// File drag-and-drop over one Chat instance: the handlers attach to the chat container, the
// overlay renders inside it (contained, never window-level), and the counter model keeps the
// overlay stable while the pointer crosses child elements.
export function useFileDrop(
  enabled: boolean,
  onFiles: (files: File[]) => void,
) {
  const [depth, setDepth] = useState(0);

  const handlers = {
    onDragEnter: (event: DragEvent) => {
      if (!enabled || !carriesFiles(event.dataTransfer.types)) return;
      event.preventDefault();
      setDepth(dragEntered);
    },
    onDragOver: (event: DragEvent) => {
      if (!enabled || !carriesFiles(event.dataTransfer.types)) return;
      event.preventDefault();
    },
    onDragLeave: (event: DragEvent) => {
      if (!enabled || !carriesFiles(event.dataTransfer.types)) return;
      setDepth(dragLeft);
    },
    onDrop: (event: DragEvent) => {
      if (!enabled || !carriesFiles(event.dataTransfer.types)) return;
      event.preventDefault();
      setDepth(dragEnded());
      const files = [...event.dataTransfer.files];
      if (files.length > 0) onFiles(files);
    },
  };

  return { dragActive: isDragActive(depth), handlers };
}

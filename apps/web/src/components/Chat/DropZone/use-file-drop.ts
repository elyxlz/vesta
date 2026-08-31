import { useState, type DragEvent } from "react";

// The overlay's visibility is a counter (enter/leave depth), never a boolean: child elements fire
// spurious dragleave events as the pointer crosses them; drop resets. Exported pure so the
// sequencing stays table-tested without DOM events.
export function dragEntered(depth: number): number {
  return depth + 1;
}

export function dragLeft(depth: number): number {
  return Math.max(0, depth - 1);
}

export function dragEnded(): number {
  return 0;
}

export function isDragActive(depth: number): boolean {
  return depth > 0;
}

// Only a drag carrying files raises the overlay; text selections and in-app drags are ignored.
export function carriesFiles(types: readonly string[]): boolean {
  return types.includes("Files");
}

// File drag-and-drop over one Chat instance: the handlers attach to the chat container, the
// overlay renders inside it (contained, never window-level).
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

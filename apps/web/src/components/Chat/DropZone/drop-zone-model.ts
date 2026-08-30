// Pure state for the file drop overlay. Child elements fire spurious dragleave events as the
// pointer crosses them, so the overlay's visibility is a counter (enter/leave depth), never a
// boolean; drop and a cancelled drag reset it.

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

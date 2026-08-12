// How a timeline point's size is worded: vestad reports it in bytes, which does not read as a size
// until it is scaled here. The stamp beside it is parsed by `@vesta/core`, which owns that form.

const BYTES_PER_KB = 1024;
const BYTES_PER_MB = BYTES_PER_KB * 1024;
const BYTES_PER_GB = BYTES_PER_MB * 1024;

export function formatSnapshotSize(bytes: number): string {
  if (bytes < BYTES_PER_KB) return `${String(bytes)} B`;
  if (bytes < BYTES_PER_MB) return `${(bytes / BYTES_PER_KB).toFixed(1)} KB`;
  if (bytes < BYTES_PER_GB) return `${(bytes / BYTES_PER_MB).toFixed(1)} MB`;
  return `${(bytes / BYTES_PER_GB).toFixed(1)} GB`;
}

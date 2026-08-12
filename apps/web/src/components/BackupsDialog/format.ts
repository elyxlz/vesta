// How a timeline point is worded: vestad stamps every snapshot with restic's compact UTC form
// (`20260529-040001`) and reports its size in bytes, and neither reads as a moment or a size until
// it is parsed here.

const COMPACT_STAMP = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/;
const BYTES_PER_KB = 1024;
const BYTES_PER_MB = BYTES_PER_KB * 1024;
const BYTES_PER_GB = BYTES_PER_MB * 1024;

export function parseSnapshotStamp(createdAt: string): Date | null {
  const parts = COMPACT_STAMP.exec(createdAt.trim());
  if (!parts) return null;
  const [, year, month, day, hour, minute, second] = parts;
  const epochMs = Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    Number(second),
  );
  return Number.isNaN(epochMs) ? null : new Date(epochMs);
}

/// The point's moment in the reader's own timezone; an unrecognized stamp is shown as it came.
export function formatSnapshotStamp(createdAt: string): string {
  const at = parseSnapshotStamp(createdAt);
  if (at === null) return createdAt;
  const date = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(at);
  const time = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(at);
  return `${date} · ${time}`;
}

export function formatSnapshotSize(bytes: number): string {
  if (bytes < BYTES_PER_KB) return `${String(bytes)} B`;
  if (bytes < BYTES_PER_MB) return `${(bytes / BYTES_PER_KB).toFixed(1)} KB`;
  if (bytes < BYTES_PER_GB) return `${(bytes / BYTES_PER_MB).toFixed(1)} MB`;
  return `${(bytes / BYTES_PER_GB).toFixed(1)} GB`;
}

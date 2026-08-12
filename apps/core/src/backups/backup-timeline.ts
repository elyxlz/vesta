import { compareReleaseVersions } from "../protocol/release-version"

// What made a snapshot, as vestad tags it on the wire, plus the bucket a kind this client has no
// copy for lands in. A new kind ships without a client bump, so `unknown` is the normal case for
// an older app rather than a wire error.
export type BackupKind = "periodic" | "manual" | "pre_update" | "pre_restore" | "unknown"

// The one place `backup_type` stops being a plain string. Both apps read the raw wire value, and
// this owns the narrowing so neither one asserts a kind it has not checked.
export function parseBackupKind(value: string): BackupKind {
  switch (value) {
    case "periodic":
    case "manual":
    case "pre_update":
    case "pre_restore":
      return value
    default:
      return "unknown"
  }
}

// A backup row from the gateway, narrowed to what a timeline reads. `created_at` is restic's
// compact form (`20260529-040001`), `from_version` carries a `v` prefix and `vestad_version`
// does not, which is why only the latter is ever compared.
export interface BackupTimelineRow {
  id: string
  created_at: string
  backup_type: BackupKind
  size: number
  from_version?: string | null
  vestad_version?: string | null
}

// What restoring a snapshot means for the user: the gateway refuses state a newer vestad wrote,
// takes older state behind a confirm, and anything it cannot compare restores plainly.
export type RestoreEligibility = "ok" | "older" | "newer"

export interface BackupTimelinePoint {
  id: string
  createdAt: string
  kind: BackupKind
  label: string
  size: number
  eligibility: RestoreEligibility
  vestadVersion: string | null
}

// The words for a snapshot, shared so web and mobile cannot drift apart. Adding a kind is a
// compile error here rather than a raw `pre_restore` reaching the user on one surface.
function backupLabel(kind: BackupKind, fromVersion: string | null): string {
  switch (kind) {
    case "periodic":
      return "Automatic"
    case "manual":
      return "Manual"
    case "pre_update":
      return fromVersion === null || fromVersion === ""
        ? "Before update"
        : `Before update ${fromVersion}`
    case "pre_restore":
      return "Safety"
    case "unknown":
      return "Backup"
  }
}

// Fails open exactly as the version window does: an absent stamp or an unparseable version on
// either side restores plainly, so a legacy snapshot is never presented as a hazard.
function restoreEligibility(
  vestadVersion: string | null,
  gatewayVersion: string | null,
): RestoreEligibility {
  if (vestadVersion === null || gatewayVersion === null) return "ok"
  const cmp = compareReleaseVersions(vestadVersion, gatewayVersion)
  if (cmp === null || cmp === 0) return "ok"
  return cmp > 0 ? "newer" : "older"
}

function newestFirst(left: BackupTimelinePoint, right: BackupTimelinePoint): number {
  if (left.createdAt === right.createdAt) return 0
  return left.createdAt < right.createdAt ? 1 : -1
}

export function buildBackupTimeline(
  rows: BackupTimelineRow[],
  gatewayVersion: string | null,
): BackupTimelinePoint[] {
  const points: BackupTimelinePoint[] = rows.map((row) => {
    const vestadVersion = row.vestad_version ?? null
    return {
      id: row.id,
      createdAt: row.created_at,
      kind: row.backup_type,
      label: backupLabel(row.backup_type, row.from_version ?? null),
      size: row.size,
      eligibility: restoreEligibility(vestadVersion, gatewayVersion),
      vestadVersion,
    }
  })
  // `created_at` is a compact sortable stamp, so a string compare orders by time. The sort is
  // stable, so snapshots sharing a stamp keep the order the gateway listed them in.
  return points.sort(newestFirst)
}

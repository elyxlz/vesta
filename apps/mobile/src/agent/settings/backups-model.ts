import {
  buildBackupTimeline,
  formatSnapshotStamp,
  parseBackupKind,
  type AgentRequest,
  type BackupTimelinePoint,
  type BackupTimelineRow,
  BackupInfo,
} from "@vesta/core";

// The gateway refuses a snapshot a newer vestad wrote, so the point says why before the user taps.
export const NEWER_REFUSAL =
  "Made by a newer vestad. Update the gateway to restore this point.";

// Everything a native confirm shows: the alert has no surrounding context, so the prompt carries
// its own wording and how heavy the confirming button reads.
export interface ConfirmPrompt {
  title: string;
  body: string;
  action: string;
  destructive: boolean;
}

// The wire's `backup_type` is a plain string; core owns the narrowing and the unknown fallback.
function timelineRows(backups: BackupInfo[]): BackupTimelineRow[] {
  return backups.map((backup) => ({
    id: backup.id,
    created_at: backup.created_at,
    backup_type: parseBackupKind(backup.backup_type),
    size: backup.size,
    from_version: backup.from_version,
    vestad_version: backup.vestad_version,
  }));
}

// The roster carries no gateway version until the sync socket's first tree lands, which core reads
// as the unknown it is and clears every point for restore.
export function backupTimeline(
  backups: BackupInfo[],
  gatewayVersion: string | undefined,
): BackupTimelinePoint[] {
  return buildBackupTimeline(timelineRows(backups), gatewayVersion ?? null);
}

function pointLine(point: BackupTimelinePoint): string {
  return `${point.label} · ${formatSnapshotStamp(point.createdAt)}`;
}

export function restorePrompt(
  point: BackupTimelinePoint,
  agentName: string,
  gatewayVersion: string | undefined,
): ConfirmPrompt {
  const lines = [
    pointLine(point),
    `This saves a safety snapshot first, then returns ${agentName} to this point and restarts them.`,
  ];
  // "older" is decided by comparing these two versions, so reaching it means both are known.
  if (point.eligibility === "older") {
    lines.push(
      `This snapshot comes from vestad ${point.vestadVersion}, and the gateway runs ${gatewayVersion}. The first boot after the restore runs migrations to converge the difference.`,
    );
  }
  return {
    title: "Restore this snapshot?",
    body: lines.join("\n\n"),
    action: "Restore",
    destructive: false,
  };
}

export type BackupAction = "create" | "restore" | "delete";

// The request this client holds on the agent while a backup action runs. Deleting a snapshot is
// not an agent lifecycle operation (vestad publishes none for it), so the orb never reads as
// busy while one is removed.
export function backupRequest(action: BackupAction): AgentRequest | null {
  switch (action) {
    case "create":
      return "backing-up";
    case "restore":
      return "restoring";
    case "delete":
      return null;
  }
}

export function deletePrompt(point: BackupTimelinePoint): ConfirmPrompt {
  return {
    title: "Delete this snapshot?",
    body: [
      pointLine(point),
      "This removes the snapshot for good. It cannot be undone.",
    ].join("\n\n"),
    action: "Delete",
    destructive: true,
  };
}

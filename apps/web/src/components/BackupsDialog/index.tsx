import { useEffect, useMemo, useState } from "react";
import {
  buildBackupTimeline,
  parseBackupKind,
  type BackupTimelinePoint,
  type BackupTimelineRow,
} from "@vesta/core";
import type { BackupInfo } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useGateway } from "@/providers/GatewayProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { formatSnapshotSize, formatSnapshotStamp } from "./format";

// The gateway refuses a snapshot a newer vestad wrote, so the point says why before the user asks.
const NEWER_REFUSAL = "made by a newer vestad; update the gateway first";

// Restoring and deleting are both irreversible, so neither runs straight off a timeline point.
interface PendingAction {
  point: BackupTimelinePoint;
  kind: "restore" | "delete";
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

function TimelinePoint({
  point,
  disabled,
  onRestore,
  onDelete,
}: {
  point: BackupTimelinePoint;
  disabled: boolean;
  onRestore: () => void;
  onDelete: () => void;
}) {
  const refused = point.eligibility === "newer";
  return (
    <li className="flex min-w-0 items-center gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <span className="truncate font-medium">
          {formatSnapshotStamp(point.createdAt)}
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="secondary" className="lowercase">
            {point.label}
          </Badge>
          {formatSnapshotSize(point.size)}
        </span>
        {refused && (
          <span className="text-xs text-muted-foreground">{NEWER_REFUSAL}</span>
        )}
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <Button size="sm" disabled={disabled || refused} onClick={onRestore}>
          restore
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={disabled}
          onClick={onDelete}
        >
          delete
        </Button>
      </div>
    </li>
  );
}

function ConfirmStep({
  agentName,
  pending,
  gatewayVersion,
  onCancel,
  onConfirm,
}: {
  agentName: string;
  pending: PendingAction;
  gatewayVersion: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { point, kind } = pending;
  const restoring = kind === "restore";
  const olderVersion =
    restoring && point.eligibility === "older" ? point.vestadVersion : null;
  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {restoring ? "restore this snapshot?" : "delete this snapshot?"}
        </DialogTitle>
        <DialogDescription>
          <span className="lowercase">{point.label}</span> ·{" "}
          {formatSnapshotStamp(point.createdAt)}
        </DialogDescription>
      </DialogHeader>
      <div className="flex min-w-0 flex-col gap-2 text-sm text-muted-foreground">
        {restoring ? (
          <p>
            this saves a safety snapshot first, then returns {agentName} to this
            point and restarts them.
          </p>
        ) : (
          <p>this removes the snapshot for good. it can&apos;t be undone.</p>
        )}
        {olderVersion !== null && (
          <p>
            this snapshot comes from vestad {olderVersion}, and the gateway runs{" "}
            {gatewayVersion}. the first boot after the restore runs migrations
            to converge the difference.
          </p>
        )}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          cancel
        </Button>
        <Button
          variant={restoring ? "default" : "destructive"}
          onClick={onConfirm}
        >
          {restoring ? "restore" : "delete"}
        </Button>
      </DialogFooter>
    </>
  );
}

// Mounted only while the dialog is open, so the fetch runs once per open and the pending
// confirmation never survives a close.
function BackupsDialogBody({ onClose }: { onClose: () => void }) {
  const {
    name,
    backups,
    isBusy,
    backup,
    refreshBackups,
    restore,
    removeBackup,
  } = useSelectedAgent();
  const { gatewayVersion } = useGateway();
  const [pending, setPending] = useState<PendingAction | null>(null);

  useEffect(() => {
    void refreshBackups();
  }, [refreshBackups]);

  const points = useMemo(
    () =>
      buildBackupTimeline(
        timelineRows(backups),
        gatewayVersion === "" ? null : gatewayVersion,
      ),
    [backups, gatewayVersion],
  );

  if (pending !== null) {
    return (
      <ConfirmStep
        agentName={name}
        pending={pending}
        gatewayVersion={gatewayVersion}
        onCancel={() => {
          setPending(null);
        }}
        onConfirm={() => {
          setPending(null);
          if (pending.kind === "restore") {
            restore(pending.point.id);
            onClose();
          } else {
            removeBackup(pending.point.id);
          }
        }}
      />
    );
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>backups for {name}</DialogTitle>
        <DialogDescription>
          back up {name} now, or return them to an earlier point. a backup
          pauses them for a few seconds.
        </DialogDescription>
      </DialogHeader>
      {points.length === 0 ? (
        <p className="text-sm text-muted-foreground">no snapshots yet.</p>
      ) : (
        <ul className="grid max-h-[45vh] min-w-0 gap-4 overflow-y-auto">
          {points.map((point) => (
            <TimelinePoint
              key={point.id}
              point={point}
              disabled={isBusy}
              onRestore={() => {
                setPending({ point, kind: "restore" });
              }}
              onDelete={() => {
                setPending({ point, kind: "delete" });
              }}
            />
          ))}
        </ul>
      )}
      <DialogFooter>
        <Button disabled={isBusy} onClick={backup}>
          back up now
        </Button>
      </DialogFooter>
    </>
  );
}

export function BackupsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog drawerOnMobile open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" showCloseButton>
        <BackupsDialogBody
          onClose={() => {
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

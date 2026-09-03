import { useEffect, useMemo, useState } from "react";
import { Trash2 } from "lucide-react";
import {
  buildBackupTimeline,
  formatSnapshotStamp,
  parseBackupKind,
  type BackupTimelinePoint,
  type BackupTimelineRow,
  type BackupInfo,
} from "@vesta/core";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/Dialog";
import { useGateway } from "@/providers/GatewayProvider/context";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { errorMessage } from "@/lib/utils";
import { formatSnapshotSize } from "./format";

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
    <li className="-mx-2 flex min-w-0 items-center gap-3 rounded-md px-2 py-2 odd:bg-foreground/[0.07]">
      <div className="flex min-w-0 flex-col gap-1">
        <span className="truncate font-medium">
          {formatSnapshotStamp(point.createdAt)}
        </span>
        <span className="min-w-0 truncate text-xs text-muted-foreground">
          <span className="lowercase">{point.label}</span> ·{" "}
          {formatSnapshotSize(point.size)}
        </span>
        {refused && (
          <span className="text-xs text-muted-foreground">{NEWER_REFUSAL}</span>
        )}
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={disabled || refused}
          onClick={onRestore}
        >
          restore
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          disabled={disabled}
          onClick={onDelete}
          aria-label="delete snapshot"
        >
          <Trash2 />
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
    backupsFailed,
    isBusy,
    request,
    backup,
    refreshBackups,
    restore,
    removeBackup,
  } = useSelectedAgent();
  const { gatewayVersion } = useGateway();
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState("");

  useEffect(() => {
    void refreshBackups();
  }, [refreshBackups]);

  const confirmDelete = async (id: string) => {
    setDeletingId(id);
    setDeleteError("");
    try {
      await removeBackup(id);
    } catch (e: unknown) {
      setDeleteError(errorMessage(e, "delete backup failed"));
    } finally {
      setDeletingId(null);
    }
  };

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
            void confirmDelete(pending.point.id);
          }
        }}
      />
    );
  }

  return (
    <>
      <DialogHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-2 text-left">
            <DialogTitle>backups for {name}</DialogTitle>
            <DialogDescription>
              back up now, or restore an earlier point. a backup pauses them
              briefly.
            </DialogDescription>
          </div>
          <Button
            size="sm"
            className="-mt-2 mr-8 shrink-0"
            disabled={isBusy}
            onClick={backup}
          >
            {request === "backing-up" ? (
              <Spinner className="size-4" />
            ) : (
              "back up"
            )}
          </Button>
        </div>
      </DialogHeader>
      {points.length === 0 ? (
        // A read that failed and an agent with no history both leave the timeline empty, so the
        // read's outcome picks the words; reopening the dialog retries.
        <p className="text-sm text-muted-foreground">
          {backupsFailed ? "couldn't load snapshots." : "no snapshots yet."}
        </p>
      ) : (
        <ul className="flex min-w-0 flex-col">
          {points.map((point) => (
            <TimelinePoint
              key={point.id}
              point={point}
              disabled={isBusy || deletingId !== null}
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
      {deleteError && <p className="text-sm text-destructive">{deleteError}</p>}
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
      <DialogContent className="max-h-[60vh] sm:max-w-lg" showCloseButton>
        <BackupsDialogBody
          onClose={() => {
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

import { AnimatePresence, motion } from "motion/react";
import { RotateCcw, WifiOff, X } from "lucide-react";
import {
  attachmentKind,
  draftTotalBytes,
  formatBytes,
  type DraftAttachment,
  type UploadErrorReason,
} from "@vesta/core";
import { ATTACHMENT_KIND_ICON } from "../ChatBubble/AttachmentContent/kind-icon";
import { cn } from "@/lib/utils";

// The composer's draft chips: one per picked file, always showing name + size, with the upload
// state as a determinate ring (uploading), a wifi-off badge (waiting for network, auto-resumes),
// or a red retry affordance (terminal error). Two or more chips add the totals footer.

const ERROR_LABEL: Record<UploadErrorReason, string> = {
  too_large: "too large",
  unsupported_agent: "agent needs an update",
  failed: "upload failed",
  aborted: "cancelled",
};

function ProgressRing({ progress }: { progress: number }) {
  const radius = 8;
  const circumference = 2 * Math.PI * radius;
  return (
    <svg viewBox="0 0 20 20" className="size-5 -rotate-90">
      <circle
        cx="10"
        cy="10"
        r={radius}
        fill="none"
        strokeWidth="2.5"
        className="stroke-border"
      />
      <circle
        cx="10"
        cy="10"
        r={radius}
        fill="none"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - progress)}
        className="stroke-primary transition-[stroke-dashoffset] duration-300"
      />
    </svg>
  );
}

function ChipThumb({
  draft,
  preview,
}: {
  draft: DraftAttachment;
  preview: string | null;
}) {
  const kind = attachmentKind(draft.mime);
  if (preview !== null && (kind === "image" || kind === "video")) {
    return kind === "image" ? (
      <img src={preview} alt="" className="size-10 rounded-lg object-cover" />
    ) : (
      <video src={preview} muted className="size-10 rounded-lg object-cover" />
    );
  }
  const Icon = ATTACHMENT_KIND_ICON[kind];
  return (
    <span className="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
      <Icon className="size-5" />
    </span>
  );
}

function chipStatus(draft: DraftAttachment): string {
  if (draft.status === "error") return ERROR_LABEL[draft.error ?? "failed"];
  if (draft.status === "waiting") return "waiting for network";
  return formatBytes(draft.size);
}

export function AttachmentChips({
  drafts,
  previewUrl,
  onRetry,
  onRemove,
}: {
  drafts: DraftAttachment[];
  previewUrl: (localId: string) => string | null;
  onRetry: (localId: string) => void;
  onRemove: (localId: string) => void;
}) {
  if (drafts.length === 0) return null;
  return (
    <div className="order-0 basis-full pt-1 pb-1.5">
      <div className="flex flex-wrap gap-2 px-1">
        <AnimatePresence initial={false}>
          {drafts.map((draft) => (
            <motion.div
              key={draft.localId}
              layout
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className={cn(
                "relative flex items-center gap-2 rounded-xl border border-border bg-background/60 p-1.5 pr-2.5",
                draft.status === "error" && "border-destructive/50",
              )}
            >
              <span className="relative">
                <ChipThumb draft={draft} preview={previewUrl(draft.localId)} />
                {(draft.status === "uploading" ||
                  draft.status === "waiting") && (
                  <span className="absolute inset-0 flex items-center justify-center rounded-lg bg-background/60">
                    {draft.status === "waiting" ? (
                      <WifiOff className="size-4 text-muted-foreground" />
                    ) : (
                      <ProgressRing progress={draft.progress} />
                    )}
                  </span>
                )}
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="max-w-36 truncate text-xs font-medium">
                  {draft.name}
                </span>
                <span
                  className={cn(
                    "text-xs text-muted-foreground",
                    draft.status === "error" && "text-destructive",
                  )}
                >
                  {chipStatus(draft)}
                </span>
              </span>
              {draft.status === "error" && (
                <button
                  type="button"
                  aria-label={`retry uploading ${draft.name}`}
                  onClick={() => {
                    onRetry(draft.localId);
                  }}
                  className="rounded-full p-1 text-muted-foreground hover:bg-accent"
                >
                  <RotateCcw className="size-3.5" />
                </button>
              )}
              <button
                type="button"
                aria-label={`remove ${draft.name}`}
                onClick={() => {
                  onRemove(draft.localId);
                }}
                className="absolute -top-1.5 -right-1.5 rounded-full border border-border bg-popover p-0.5 text-muted-foreground shadow-sm hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
      {drafts.length > 1 && (
        <div className="px-1.5 pt-1 text-xs text-muted-foreground">
          {drafts.length} files · {formatBytes(draftTotalBytes(drafts))}
        </div>
      )}
    </div>
  );
}

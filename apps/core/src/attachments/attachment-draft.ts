import {
  MAX_ATTACHMENTS_PER_MESSAGE,
  type ChatAttachment,
} from "./attachment-model";
import type { UploadErrorReason } from "./upload";

// The composer's draft list as pure data, shared by every client: one entry per picked file, moved
// through uploading/waiting/uploaded/error by the upload engine's callbacks. Views render chips from
// this; the send gate is draftsReady.

export type DraftStatus = "uploading" | "waiting" | "uploaded" | "error";

export interface DraftAttachment {
  localId: string;
  name: string;
  mime: string;
  size: number;
  status: DraftStatus;
  // Bytes sent over bytes total, 0..1; uploaded drafts read 1.
  progress: number;
  attachment?: ChatAttachment;
  error?: UploadErrorReason;
}

export interface DraftFile {
  name: string;
  mime: string;
  size: number;
}

// Add a picked file as an uploading draft, or null when the message is already at the cap.
export function addDraft(
  drafts: DraftAttachment[],
  file: DraftFile,
  localId: string,
): DraftAttachment[] | null {
  if (drafts.length >= MAX_ATTACHMENTS_PER_MESSAGE) return null;
  return [
    ...drafts,
    {
      localId,
      name: file.name,
      mime: file.mime,
      size: file.size,
      status: "uploading",
      progress: 0,
    },
  ];
}

function update(
  drafts: DraftAttachment[],
  localId: string,
  change: (draft: DraftAttachment) => DraftAttachment,
): DraftAttachment[] {
  return drafts.map((draft) =>
    draft.localId === localId ? change(draft) : draft,
  );
}

export function setDraftProgress(
  drafts: DraftAttachment[],
  localId: string,
  sent: number,
  total: number,
): DraftAttachment[] {
  return update(drafts, localId, (draft) => ({
    ...draft,
    status: "uploading",
    progress: total > 0 ? Math.min(sent / total, 1) : 1,
  }));
}

export function setDraftWaiting(
  drafts: DraftAttachment[],
  localId: string,
): DraftAttachment[] {
  return update(drafts, localId, (draft) => ({ ...draft, status: "waiting" }));
}

export function finalizeDraft(
  drafts: DraftAttachment[],
  localId: string,
  attachment: ChatAttachment,
): DraftAttachment[] {
  return update(drafts, localId, (draft) => ({
    ...draft,
    status: "uploaded",
    progress: 1,
    attachment,
  }));
}

export function failDraft(
  drafts: DraftAttachment[],
  localId: string,
  error: UploadErrorReason,
): DraftAttachment[] {
  return update(drafts, localId, (draft) => ({
    ...draft,
    status: "error",
    error,
  }));
}

export function removeDraft(
  drafts: DraftAttachment[],
  localId: string,
): DraftAttachment[] {
  return drafts.filter((draft) => draft.localId !== localId);
}

// The send gate: something to send, and nothing still moving or broken.
export function draftsReady(drafts: DraftAttachment[]): boolean {
  return (
    drafts.length > 0 && drafts.every((draft) => draft.status === "uploaded")
  );
}

export function uploadedIds(drafts: DraftAttachment[]): string[] {
  return drafts.flatMap((draft) =>
    draft.attachment ? [draft.attachment.id] : [],
  );
}

export function uploadedAttachments(
  drafts: DraftAttachment[],
): ChatAttachment[] {
  return drafts.flatMap((draft) =>
    draft.attachment ? [draft.attachment] : [],
  );
}

export function draftTotalBytes(drafts: DraftAttachment[]): number {
  return drafts.reduce((total, draft) => total + draft.size, 0);
}

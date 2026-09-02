import { useCallback } from "react";
import {
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENTS_PER_MESSAGE,
  UploadError,
  addDraft,
  agentHoldKey,
  createKeyedHoldStore,
  draftsReady,
  failDraft,
  finalizeDraft,
  formatBytes,
  removeDraft,
  setDraftProgress,
  setDraftWaiting,
  uploadAttachment,
  uploadedAttachments,
  type ChatAttachment,
  type Connectivity,
  type DraftAttachment,
  type UploadDeps,
  type UploadHandle,
  type UploadMeta,
} from "@vesta/core";
import { useHeld } from "@vesta/core/react";
import { getConnection } from "@/lib/connection";
import { httpClient } from "@/api/client";
import { useToastStore } from "@/stores/use-toast";

// Composer attachment drafts, held per agent and per gateway exactly like the text draft
// (use-chat-draft), so the desktop panel and the fullscreen chat share one list and leaving the
// route never cancels an upload. The engine, files, and preview object URLs are module state keyed
// by localId; the hold store carries only the renderable DraftAttachment list.
const attachmentDrafts = createKeyedHoldStore<DraftAttachment[]>();
const pickedFiles = new Map<string, File>();
const uploadHandles = new Map<string, UploadHandle>();
const previewUrls = new Map<string, string>();

const browserConnectivity: Connectivity = {
  isOnline: () => navigator.onLine,
  onChange: (callback) => {
    const onOnline = () => {
      callback(true);
    };
    const onOffline = () => {
      callback(false);
    };
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  },
};

const uploadDeps: UploadDeps = {
  connectivity: browserConnectivity,
  setTimer: (fn, ms) => window.setTimeout(fn, ms),
  clearTimer: (handle) => {
    window.clearTimeout(handle);
  },
  now: () => Date.now(),
};

type MediaProbe = Pick<UploadMeta, "width" | "height" | "duration_secs">;

function probeVideo(file: File): Promise<MediaProbe> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    const done = (probe: MediaProbe) => {
      URL.revokeObjectURL(url);
      resolve(probe);
    };
    const timeout = window.setTimeout(() => {
      done({});
    }, 3000);
    video.preload = "metadata";
    video.onloadedmetadata = () => {
      window.clearTimeout(timeout);
      done({
        width: video.videoWidth || undefined,
        height: video.videoHeight || undefined,
        duration_secs: Number.isFinite(video.duration)
          ? video.duration
          : undefined,
      });
    };
    video.onerror = () => {
      window.clearTimeout(timeout);
      done({});
    };
    video.src = url;
  });
}

// Best-effort dimensions: images pre-size their bubbles (no scroll jitter on load), videos add
// duration. Any failure just means no pre-sizing.
async function measureMedia(file: File): Promise<MediaProbe> {
  try {
    if (file.type.startsWith("image/")) {
      const bitmap = await createImageBitmap(file);
      const probe = { width: bitmap.width, height: bitmap.height };
      bitmap.close();
      return probe;
    }
    if (file.type.startsWith("video/")) return await probeVideo(file);
  } catch {
    // Not measurable (exotic format): upload without dimensions.
  }
  return {};
}

function draftExists(key: string, localId: string): boolean {
  return (attachmentDrafts.read(key) ?? []).some(
    (draft) => draft.localId === localId,
  );
}

// Fold one draft's cell. Returns false without touching the store when the draft is gone
// (removed, or its whole cell LRU-evicted): writing then would resurrect an empty cell and
// evict someone else's live drafts.
function mutateDraft(
  key: string,
  localId: string,
  fold: (drafts: DraftAttachment[]) => DraftAttachment[],
): boolean {
  const current = attachmentDrafts.read(key) ?? [];
  if (!current.some((draft) => draft.localId === localId)) return false;
  attachmentDrafts.persist(key, fold(current));
  return true;
}

// Free every per-draft resource outside the store: the running engine, the picked File, and the
// preview object URL. Shared by remove, clear, and orphan detection.
function release(localId: string) {
  uploadHandles.get(localId)?.abort();
  uploadHandles.delete(localId);
  pickedFiles.delete(localId);
  const preview = previewUrls.get(localId);
  if (preview !== undefined) {
    URL.revokeObjectURL(preview);
    previewUrls.delete(localId);
  }
}

function discard(key: string, localId: string) {
  release(localId);
  mutateDraft(key, localId, (drafts) => removeDraft(drafts, localId));
}

function startUpload(key: string, agent: string, localId: string, file: File) {
  void measureMedia(file).then((probe) => {
    // The chip may have been removed while the metadata probe ran; starting now would upload a
    // blob nothing references and nothing can cancel.
    if (!draftExists(key, localId)) {
      release(localId);
      return;
    }
    const meta: UploadMeta = {
      name: file.name,
      mime: file.type || "application/octet-stream",
      size: file.size,
      ...probe,
    };
    let handle: UploadHandle | null = null;
    // A callback landing on a vanished draft means the cell was evicted from under the engine:
    // abort it and free the side state, or it would retry forever with no UI able to cancel.
    const orphaned = () => {
      handle?.abort();
      release(localId);
    };
    handle = uploadAttachment(
      httpClient,
      { agent, blob: file, meta },
      uploadDeps,
      {
        onProgress: (sent, total) => {
          if (
            !mutateDraft(key, localId, (drafts) =>
              setDraftProgress(drafts, localId, sent, total),
            )
          )
            orphaned();
        },
        onStateChange: (state) => {
          if (state !== "waiting") return;
          if (
            !mutateDraft(key, localId, (drafts) =>
              setDraftWaiting(drafts, localId),
            )
          )
            orphaned();
        },
      },
    );
    uploadHandles.set(localId, handle);
    handle.result.then(
      (attachment) => {
        uploadHandles.delete(localId);
        mutateDraft(key, localId, (drafts) =>
          finalizeDraft(drafts, localId, attachment),
        );
      },
      (error: unknown) => {
        uploadHandles.delete(localId);
        const reason = error instanceof UploadError ? error.reason : "failed";
        if (reason === "aborted") return; // the remove/orphan that aborted already cleaned up
        if (reason === "unsupported_agent") {
          useToastStore
            .getState()
            .show("error", `${agent} needs an update to receive files`);
          discard(key, localId);
          return;
        }
        mutateDraft(key, localId, (drafts) =>
          failDraft(drafts, localId, reason),
        );
      },
    );
  });
}

function acceptFile(key: string, agent: string, file: File): boolean {
  if (file.size > MAX_ATTACHMENT_BYTES) {
    useToastStore
      .getState()
      .show(
        "error",
        `${file.name} is too large (${formatBytes(file.size)}, limit ${formatBytes(MAX_ATTACHMENT_BYTES)})`,
      );
    return true; // skip this file, keep taking the rest
  }
  const localId = crypto.randomUUID();
  const added = addDraft(
    attachmentDrafts.read(key) ?? [],
    {
      name: file.name,
      mime: file.type || "application/octet-stream",
      size: file.size,
    },
    localId,
  );
  if (added === null) {
    useToastStore
      .getState()
      .show(
        "error",
        `at most ${String(MAX_ATTACHMENTS_PER_MESSAGE)} files per message`,
      );
    return false;
  }
  attachmentDrafts.persist(key, added);
  pickedFiles.set(localId, file);
  if (file.type.startsWith("image/") || file.type.startsWith("video/"))
    previewUrls.set(localId, URL.createObjectURL(file));
  startUpload(key, agent, localId, file);
  return true;
}

export interface AttachmentDrafts {
  drafts: DraftAttachment[];
  addFiles: (files: File[]) => void;
  retry: (localId: string) => void;
  remove: (localId: string) => void;
  clear: () => void;
  previewUrl: (localId: string) => string | null;
  ready: boolean;
  uploaded: ChatAttachment[];
}

export function useAttachmentDrafts(agent: string): AttachmentDrafts {
  const key = agentHoldKey(agent, getConnection()?.url ?? "");
  const drafts = useHeld(attachmentDrafts, key) ?? [];

  const addFiles = useCallback(
    (files: File[]) => {
      for (const file of files) if (!acceptFile(key, agent, file)) break;
    },
    [key, agent],
  );

  const retry = useCallback(
    (localId: string) => {
      const file = pickedFiles.get(localId);
      if (!file) {
        discard(key, localId);
        return;
      }
      mutateDraft(key, localId, (current) =>
        setDraftProgress(current, localId, 0, file.size),
      );
      startUpload(key, agent, localId, file);
    },
    [key, agent],
  );

  const remove = useCallback(
    (localId: string) => {
      discard(key, localId);
    },
    [key],
  );

  const clear = useCallback(() => {
    for (const draft of attachmentDrafts.read(key) ?? [])
      release(draft.localId);
    attachmentDrafts.persist(key, []);
  }, [key]);

  const previewUrl = useCallback(
    (localId: string) => previewUrls.get(localId) ?? null,
    [],
  );

  return {
    drafts,
    addFiles,
    retry,
    remove,
    clear,
    previewUrl,
    ready: draftsReady(drafts),
    uploaded: uploadedAttachments(drafts),
  };
}

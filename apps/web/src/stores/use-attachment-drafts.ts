import { useCallback } from "react";
import {
  MAX_ATTACHMENT_BYTES,
  UploadError,
  addDraft,
  agentHoldKey,
  createKeyedHoldStore,
  draftTotalBytes,
  draftsReady,
  failDraft,
  finalizeDraft,
  formatBytes,
  removeDraft,
  setDraftProgress,
  setDraftWaiting,
  uploadAttachment,
  uploadedAttachments,
  uploadedIds,
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

function mutate(
  key: string,
  fold: (drafts: DraftAttachment[]) => DraftAttachment[],
) {
  attachmentDrafts.persist(key, fold(attachmentDrafts.read(key) ?? []));
}

function discard(key: string, localId: string) {
  uploadHandles.get(localId)?.abort();
  uploadHandles.delete(localId);
  pickedFiles.delete(localId);
  const preview = previewUrls.get(localId);
  if (preview !== undefined) {
    URL.revokeObjectURL(preview);
    previewUrls.delete(localId);
  }
  mutate(key, (drafts) => removeDraft(drafts, localId));
}

function startUpload(key: string, agent: string, localId: string, file: File) {
  void measureMedia(file).then((probe) => {
    const meta: UploadMeta = {
      name: file.name,
      mime: file.type || "application/octet-stream",
      size: file.size,
      ...probe,
    };
    const handle = uploadAttachment(httpClient, agent, file, meta, uploadDeps, {
      onProgress: (sent, total) => {
        mutate(key, (drafts) => setDraftProgress(drafts, localId, sent, total));
      },
      onStateChange: (state) => {
        if (state === "waiting")
          mutate(key, (drafts) => setDraftWaiting(drafts, localId));
      },
    });
    uploadHandles.set(localId, handle);
    handle.result.then(
      (attachment) => {
        uploadHandles.delete(localId);
        mutate(key, (drafts) => finalizeDraft(drafts, localId, attachment));
      },
      (error: unknown) => {
        uploadHandles.delete(localId);
        const reason = error instanceof UploadError ? error.reason : "failed";
        if (reason === "aborted") return; // the remove that aborted already cleaned up
        if (reason === "unsupported_agent") {
          useToastStore
            .getState()
            .show("error", `${agent} needs an update to receive files`);
          discard(key, localId);
          return;
        }
        mutate(key, (drafts) => failDraft(drafts, localId, reason));
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
    useToastStore.getState().show("error", "at most 10 files per message");
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
  uploadedIdList: string[];
  totalBytes: number;
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
      mutate(key, (current) =>
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
    for (const draft of attachmentDrafts.read(key) ?? []) {
      uploadHandles.get(draft.localId)?.abort();
      uploadHandles.delete(draft.localId);
      pickedFiles.delete(draft.localId);
      const preview = previewUrls.get(draft.localId);
      if (preview !== undefined) {
        URL.revokeObjectURL(preview);
        previewUrls.delete(draft.localId);
      }
    }
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
    uploadedIdList: uploadedIds(drafts),
    totalBytes: draftTotalBytes(drafts),
  };
}

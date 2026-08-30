import { useMemo } from "react";
import {
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENTS_PER_MESSAGE,
  UploadError,
  addDraft,
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
  type DraftAttachment,
  type HttpClient,
  type UploadDeps,
  type UploadHandle,
  type UploadMeta,
} from "@vesta/core";
import { useHeld } from "@vesta/core/react";
import * as Crypto from "expo-crypto";
import { agentHolds } from "@/holds/agent-holds";
import { netInfoConnectivity } from "./connectivity";
import { assetToBlob, type PickedAsset } from "./pick";

// Composer attachment drafts, held per agent and gateway in the shared attachments cell, so
// popping the chat screen or backgrounding never cancels an upload. The engine handles, source
// blobs, and preview uris are module state keyed by localId; the hold cell carries only the
// renderable DraftAttachment list. Ported from the web store; the swapped edges are the picked
// asset (Blob via fetch(uri)) in place of a File, NetInfo in place of navigator.onLine, and the
// controller's HttpClient.
const sourceBlobs = new Map<string, Blob>();
const sourceMeta = new Map<string, UploadMeta>();
const uploadHandles = new Map<string, UploadHandle>();
const previewUris = new Map<string, string>();

function uploadDeps(): UploadDeps {
  return {
    connectivity: netInfoConnectivity(),
    setTimer: (fn, ms) => Number(setTimeout(fn, ms)),
    clearTimer: (handle) => {
      clearTimeout(handle);
    },
    now: () => Date.now(),
  };
}

// Fold one draft's cell. Returns false without touching the store when the draft is gone
// (removed, or its whole cell LRU-evicted): writing then would resurrect an empty cell and
// evict someone else's live drafts.
function mutateDraft(
  key: string,
  localId: string,
  fold: (drafts: DraftAttachment[]) => DraftAttachment[],
): boolean {
  const current = agentHolds.attachments.read(key) ?? [];
  if (!current.some((draft) => draft.localId === localId)) return false;
  agentHolds.attachments.persist(key, fold(current));
  return true;
}

// Free every per-draft resource outside the store: the running engine, the source blob, and the
// preview uri. Shared by remove, clear, and orphan detection.
function release(localId: string) {
  uploadHandles.get(localId)?.abort();
  uploadHandles.delete(localId);
  sourceBlobs.delete(localId);
  sourceMeta.delete(localId);
  previewUris.delete(localId);
}

function discard(key: string, localId: string) {
  release(localId);
  mutateDraft(key, localId, (drafts) => removeDraft(drafts, localId));
}

function startUpload(
  key: string,
  agent: string,
  http: HttpClient,
  localId: string,
  notify: (message: string) => void,
) {
  const blob = sourceBlobs.get(localId);
  const meta = sourceMeta.get(localId);
  if (!blob || !meta) {
    discard(key, localId);
    return;
  }
  let handle: UploadHandle | null = null;
  // A callback landing on a vanished draft means the cell was evicted from under the engine:
  // abort it and free the side state, or it would retry forever with no UI able to cancel.
  const orphaned = () => {
    handle?.abort();
    release(localId);
  };
  handle = uploadAttachment(http, agent, blob, meta, uploadDeps(), {
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
        !mutateDraft(key, localId, (drafts) => setDraftWaiting(drafts, localId))
      )
        orphaned();
    },
  });
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
        notify(`${agent} needs an update to receive files`);
        discard(key, localId);
        return;
      }
      mutateDraft(key, localId, (drafts) =>
        failDraft(drafts, localId, reason),
      );
    },
  );
}

export async function acceptAsset(
  key: string,
  agent: string,
  http: HttpClient,
  asset: PickedAsset,
  notify: (message: string) => void,
): Promise<boolean> {
  let blob: Blob;
  try {
    blob = await assetToBlob(asset);
  } catch {
    notify(`couldn't read ${asset.name}`);
    return true; // skip this one, keep taking the rest
  }
  if (blob.size > MAX_ATTACHMENT_BYTES) {
    notify(
      `${asset.name} is too large (${formatBytes(blob.size)}, limit ${formatBytes(MAX_ATTACHMENT_BYTES)})`,
    );
    return true;
  }
  const localId = Crypto.randomUUID();
  const added = addDraft(
    agentHolds.attachments.read(key) ?? [],
    { name: asset.name, mime: asset.mime, size: blob.size },
    localId,
  );
  if (added === null) {
    notify(`at most ${String(MAX_ATTACHMENTS_PER_MESSAGE)} files per message`);
    return false;
  }
  agentHolds.attachments.persist(key, added);
  sourceBlobs.set(localId, blob);
  sourceMeta.set(localId, {
    name: asset.name,
    mime: asset.mime,
    size: blob.size,
    ...(asset.width ? { width: asset.width } : {}),
    ...(asset.height ? { height: asset.height } : {}),
    ...(asset.durationSecs ? { duration_secs: asset.durationSecs } : {}),
  });
  if (asset.mime.startsWith("image/") || asset.mime.startsWith("video/"))
    previewUris.set(localId, asset.uri);
  startUpload(key, agent, http, localId, notify);
  return true;
}

export interface AttachmentDraftActions {
  addAssets: (assets: PickedAsset[]) => Promise<void>;
  retry: (localId: string) => void;
  remove: (localId: string) => void;
  clear: () => void;
  previewUri: (localId: string) => string | null;
}

// The imperative half, pure module logic over the hold cell so it tests without React. The hook
// below is the one thin React binding.
export function attachmentDraftActions(
  agent: string,
  holdKey: string,
  http: HttpClient,
  notify: (message: string) => void,
): AttachmentDraftActions {
  return {
    addAssets: async (assets) => {
      for (const asset of assets)
        if (!(await acceptAsset(holdKey, agent, http, asset, notify))) break;
    },
    retry: (localId) => {
      if (!sourceBlobs.has(localId)) {
        discard(holdKey, localId);
        return;
      }
      mutateDraft(holdKey, localId, (current) =>
        setDraftProgress(
          current,
          localId,
          0,
          sourceBlobs.get(localId)?.size ?? 1,
        ),
      );
      startUpload(holdKey, agent, http, localId, notify);
    },
    remove: (localId) => {
      discard(holdKey, localId);
    },
    clear: () => {
      for (const draft of agentHolds.attachments.read(holdKey) ?? [])
        release(draft.localId);
      agentHolds.attachments.persist(holdKey, []);
    },
    previewUri: (localId) => previewUris.get(localId) ?? null,
  };
}

export interface AttachmentDrafts extends AttachmentDraftActions {
  drafts: DraftAttachment[];
  ready: boolean;
  uploaded: ChatAttachment[];
}

export function useAttachmentDrafts(
  agent: string,
  holdKey: string,
  http: HttpClient,
  notify: (message: string) => void,
): AttachmentDrafts {
  const drafts = useHeld(agentHolds.attachments, holdKey) ?? [];
  const actions = useMemo(
    () => attachmentDraftActions(agent, holdKey, http, notify),
    [agent, holdKey, http, notify],
  );
  return {
    ...actions,
    drafts,
    ready: draftsReady(drafts),
    uploaded: uploadedAttachments(drafts),
  };
}

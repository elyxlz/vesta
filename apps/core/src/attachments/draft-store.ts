import type { KeyedHoldStore } from "../holds/keyed-hold";
import type { HttpClient } from "../transport/http";
import {
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENTS_PER_MESSAGE,
  formatBytes,
} from "./attachment-model";
import {
  addDraft,
  failDraft,
  finalizeDraft,
  removeDraft,
  setDraftProgress,
  setDraftWaiting,
  type DraftAttachment,
} from "./attachment-draft";
import {
  UploadError,
  uploadAttachment,
  type Connectivity,
  type UploadHandle,
  type UploadMeta,
} from "./upload";

// One file the user picked, as the platform hands it over: its identity now, its bytes and any
// media probe on demand. `size` gates the too-large refusal before any bytes are read; `open`
// yields the blob the engine uploads; `probe` adds best-effort dimensions and duration so an image
// bubble pre-sizes and a video shows its length. `preview` is a platform URL for the chip's
// thumbnail, released through `revokePreview` when the draft goes.
export interface DraftSource {
  name: string;
  mime: string;
  size: number;
  open: () => Promise<Blob>;
  probe?: () => Promise<Pick<UploadMeta, "width" | "height" | "duration_secs">>;
  preview?: string | null;
}

export interface DraftStoreDeps {
  http: HttpClient;
  hold: KeyedHoldStore<DraftAttachment[]>;
  connectivity: Connectivity;
  makeId: () => string;
  // The user-facing refusal or failure line (a toast on every platform).
  notify: (message: string) => void;
  revokePreview?: (url: string) => void;
}

export interface DraftStore {
  // Accepts one source into the cell: false when the per-message cap refused it (the caller stops
  // taking more), true otherwise (accepted, or skipped with a notice).
  add: (key: string, agent: string, source: DraftSource) => boolean;
  retry: (key: string, agent: string, localId: string) => void;
  remove: (key: string, localId: string) => void;
  clear: (key: string) => void;
  previewUrl: (localId: string) => string | null;
}

// Composer attachment drafts, held per agent and per gateway exactly like the text draft, so every
// surface over the same key shares one list and leaving the route never cancels an upload. The
// engine, the source, and the preview are store state keyed by localId; the hold cell carries only
// the renderable DraftAttachment list.
export function createDraftStore(deps: DraftStoreDeps): DraftStore {
  const sources = new Map<string, DraftSource>();
  const handles = new Map<string, UploadHandle>();
  const previews = new Map<string, string>();

  const exists = (key: string, localId: string): boolean =>
    (deps.hold.read(key) ?? []).some((draft) => draft.localId === localId);

  // Fold one draft's cell. Returns false without touching the store when the draft is gone
  // (removed, or its whole cell LRU-evicted): writing then would resurrect an empty cell and
  // evict someone else's live drafts.
  const mutate = (
    key: string,
    localId: string,
    fold: (drafts: DraftAttachment[]) => DraftAttachment[],
  ): boolean => {
    const current = deps.hold.read(key) ?? [];
    if (!current.some((draft) => draft.localId === localId)) return false;
    deps.hold.persist(key, fold(current));
    return true;
  };

  // Free every per-draft resource outside the store: the running engine, the source, and the
  // preview. Shared by remove, clear, and orphan detection.
  const release = (localId: string): void => {
    handles.get(localId)?.abort();
    handles.delete(localId);
    sources.delete(localId);
    const preview = previews.get(localId);
    if (preview !== undefined) {
      deps.revokePreview?.(preview);
      previews.delete(localId);
    }
  };

  const discard = (key: string, localId: string): void => {
    release(localId);
    mutate(key, localId, (drafts) => removeDraft(drafts, localId));
  };

  const startUpload = (key: string, agent: string, localId: string): void => {
    const source = sources.get(localId);
    if (!source) {
      discard(key, localId);
      return;
    }
    void Promise.all([source.open(), source.probe?.() ?? {}]).then(
      ([blob, probe]) => {
        // The chip may have been removed while the source opened; starting now would upload a
        // blob nothing references and nothing can cancel.
        if (!exists(key, localId)) {
          release(localId);
          return;
        }
        const meta: UploadMeta = {
          name: source.name,
          mime: source.mime,
          size: blob.size,
          ...probe,
        };
        let handle: UploadHandle | null = null;
        // A callback landing on a vanished draft means the cell was evicted from under the engine:
        // abort it and free the side state, or it would retry forever with no UI able to cancel.
        const orphaned = (): void => {
          handle?.abort();
          release(localId);
        };
        handle = uploadAttachment(
          deps.http,
          { agent, blob, meta },
          { connectivity: deps.connectivity, now: () => Date.now() },
          {
            onProgress: (sent, total) => {
              if (
                !mutate(key, localId, (drafts) =>
                  setDraftProgress(drafts, localId, sent, total),
                )
              )
                orphaned();
            },
            onStateChange: (state) => {
              if (state !== "waiting") return;
              if (
                !mutate(key, localId, (drafts) =>
                  setDraftWaiting(drafts, localId),
                )
              )
                orphaned();
            },
          },
        );
        handles.set(localId, handle);
        handle.result.then(
          (attachment) => {
            handles.delete(localId);
            mutate(key, localId, (drafts) =>
              finalizeDraft(drafts, localId, attachment),
            );
          },
          (error: unknown) => {
            handles.delete(localId);
            const reason =
              error instanceof UploadError ? error.reason : "failed";
            // The remove or orphan that aborted already cleaned up.
            if (reason === "aborted") return;
            if (reason === "unsupported_agent") {
              deps.notify(`${agent} needs an update to receive files`);
              discard(key, localId);
              return;
            }
            mutate(key, localId, (drafts) =>
              failDraft(drafts, localId, reason),
            );
          },
        );
      },
      () => {
        deps.notify(`couldn't read ${source.name}`);
        discard(key, localId);
      },
    );
  };

  return {
    add: (key, agent, source) => {
      if (source.size > MAX_ATTACHMENT_BYTES) {
        deps.notify(
          `${source.name} is too large (${formatBytes(source.size)}, limit ${formatBytes(MAX_ATTACHMENT_BYTES)})`,
        );
        return true;
      }
      const localId = deps.makeId();
      const added = addDraft(
        deps.hold.read(key) ?? [],
        { name: source.name, mime: source.mime, size: source.size },
        localId,
      );
      if (added === null) {
        deps.notify(
          `at most ${String(MAX_ATTACHMENTS_PER_MESSAGE)} files per message`,
        );
        return false;
      }
      deps.hold.persist(key, added);
      sources.set(localId, source);
      if (source.preview != null) previews.set(localId, source.preview);
      startUpload(key, agent, localId);
      return true;
    },
    retry: (key, agent, localId) => {
      const source = sources.get(localId);
      if (!source) {
        discard(key, localId);
        return;
      }
      mutate(key, localId, (current) =>
        setDraftProgress(current, localId, 0, source.size),
      );
      startUpload(key, agent, localId);
    },
    remove: discard,
    clear: (key) => {
      for (const draft of deps.hold.read(key) ?? []) release(draft.localId);
      deps.hold.persist(key, []);
    },
    previewUrl: (localId) => previews.get(localId) ?? null,
  };
}

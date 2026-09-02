import { useMemo } from "react";
import type { ChatAttachment } from "../attachments/attachment-model";
import {
  draftsReady,
  uploadedAttachments,
  type DraftAttachment,
} from "../attachments/attachment-draft";
import type { DraftSource, DraftStore } from "../attachments/draft-store";
import type { KeyedHoldStore } from "../holds/keyed-hold";
import { useHeld } from "./use-held";

export interface AttachmentDrafts {
  drafts: DraftAttachment[];
  // Accepts sources in order, stopping at the first the per-message cap refuses.
  addSources: (sources: DraftSource[]) => void;
  retry: (localId: string) => void;
  remove: (localId: string) => void;
  clear: () => void;
  previewUrl: (localId: string) => string | null;
  ready: boolean;
  uploaded: ChatAttachment[];
}

// The composer's view of one hold cell: the renderable list plus the actions bound to its key.
export function useAttachmentDrafts(
  store: DraftStore,
  hold: KeyedHoldStore<DraftAttachment[]>,
  key: string,
  agent: string,
): AttachmentDrafts {
  const drafts = useHeld(hold, key) ?? [];
  const actions = useMemo(
    () => ({
      addSources: (sources: DraftSource[]) => {
        for (const source of sources) if (!store.add(key, agent, source)) break;
      },
      retry: (localId: string) => {
        store.retry(key, agent, localId);
      },
      remove: (localId: string) => {
        store.remove(key, localId);
      },
      clear: () => {
        store.clear(key);
      },
      previewUrl: store.previewUrl,
    }),
    [store, key, agent],
  );
  return {
    ...actions,
    drafts,
    ready: draftsReady(drafts),
    uploaded: uploadedAttachments(drafts),
  };
}

import { useCallback, useMemo } from "react";
import {
  createDraftStore,
  type ChatAttachment,
  type DraftAttachment,
  type DraftSource,
  type DraftStore,
  type HttpClient,
} from "@vesta/core";
import { useAttachmentDrafts as useDraftCell } from "@vesta/core/react";
import * as Crypto from "expo-crypto";
import { agentHolds } from "@/holds/agent-holds";
import { netInfoConnectivity } from "./connectivity";
import { assetToBlob, type PickedAsset } from "./pick";

// The mobile binding of core's draft store: NetInfo connectivity, expo-crypto ids, the picked
// asset read into a Blob, and the asset uri as the chip's preview (images only: expo-image on iOS
// cannot decode a frame out of a file:// video, so a video chip takes the kind-icon tile).
async function assetSource(
  asset: PickedAsset,
  notify: (message: string) => void,
): Promise<DraftSource | null> {
  let blob: Blob;
  try {
    blob = await assetToBlob(asset);
  } catch {
    notify(`couldn't read ${asset.name}`);
    return null;
  }
  return {
    name: asset.name,
    mime: asset.mime,
    size: blob.size,
    open: () => Promise.resolve(blob),
    probe: () =>
      Promise.resolve({
        ...(asset.width ? { width: asset.width } : {}),
        ...(asset.height ? { height: asset.height } : {}),
        ...(asset.durationSecs ? { duration_secs: asset.durationSecs } : {}),
      }),
    preview: asset.mime.startsWith("image/") ? asset.uri : null,
  };
}

// One store per (http, notify) pair: the controller epoch owns the client, so a gateway switch
// rebuilds it, while the hold cell keeps the drafts across that rebuild.
export function draftStoreFor(
  http: HttpClient,
  notify: (message: string) => void,
): DraftStore {
  return createDraftStore({
    http,
    hold: agentHolds.attachments,
    connectivity: netInfoConnectivity(),
    makeId: () => Crypto.randomUUID(),
    notify,
  });
}

export interface AttachmentDrafts {
  drafts: DraftAttachment[];
  addAssets: (assets: PickedAsset[]) => Promise<void>;
  retry: (localId: string) => void;
  remove: (localId: string) => void;
  clear: () => void;
  previewUri: (localId: string) => string | null;
  ready: boolean;
  uploaded: ChatAttachment[];
}

export function useAttachmentDrafts(
  agent: string,
  holdKey: string,
  http: HttpClient,
  notify: (message: string) => void,
): AttachmentDrafts {
  const store = useMemo(() => draftStoreFor(http, notify), [http, notify]);
  const { addSources, previewUrl, ...cell } = useDraftCell(
    store,
    agentHolds.attachments,
    holdKey,
    agent,
  );
  const addAssets = useCallback(
    async (assets: PickedAsset[]) => {
      const sources: DraftSource[] = [];
      for (const asset of assets) {
        const source = await assetSource(asset, notify);
        if (source) sources.push(source);
      }
      addSources(sources);
    },
    [addSources, notify],
  );
  return { ...cell, addAssets, previewUri: previewUrl };
}

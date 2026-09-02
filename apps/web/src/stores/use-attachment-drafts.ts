import { useCallback } from "react";
import {
  agentHoldKey,
  createDraftStore,
  createKeyedHoldStore,
  type Connectivity,
  type DraftAttachment,
  type DraftSource,
  type UploadMeta,
} from "@vesta/core";
import {
  useAttachmentDrafts as useDraftCell,
  type AttachmentDrafts as DraftCell,
} from "@vesta/core/react";
import { getConnection } from "@/lib/connection";
import { httpClient } from "@/api/client";
import { useToastStore } from "@/stores/use-toast";

// The web binding of core's draft store: the browser's connectivity, object-URL previews, and
// the media probe that pre-sizes an image bubble; the store owns everything else.
const attachmentDrafts = createKeyedHoldStore<DraftAttachment[]>();

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

const draftStore = createDraftStore({
  http: httpClient,
  hold: attachmentDrafts,
  connectivity: browserConnectivity,
  makeId: () => crypto.randomUUID(),
  notify: (message) => {
    useToastStore.getState().show("error", message);
  },
  revokePreview: (url) => {
    URL.revokeObjectURL(url);
  },
});

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

function fileSource(file: File): DraftSource {
  const mime = file.type || "application/octet-stream";
  const media =
    file.type.startsWith("image/") || file.type.startsWith("video/");
  return {
    name: file.name,
    mime,
    size: file.size,
    open: () => Promise.resolve(file),
    probe: () => measureMedia(file),
    preview: media ? URL.createObjectURL(file) : null,
  };
}

export interface AttachmentDrafts extends Omit<DraftCell, "addSources"> {
  addFiles: (files: File[]) => void;
}

export function useAttachmentDrafts(agent: string): AttachmentDrafts {
  const key = agentHoldKey(agent, getConnection()?.url ?? "");
  const { addSources, ...cell } = useDraftCell(
    draftStore,
    attachmentDrafts,
    key,
    agent,
  );
  const addFiles = useCallback(
    (files: File[]) => {
      addSources(files.map(fileSource));
    },
    [addSources],
  );
  return { ...cell, addFiles };
}

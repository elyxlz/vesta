import { create } from "zustand";
import { type ChatAttachment } from "@vesta/core";
import { attachmentRemoved, downloadAttachment } from "@/lib/download";
import { useToastStore } from "@/stores/use-toast";

// One attachment download's live state. The store outlives both the viewer overlay and the bubble,
// so a download started in the viewer keeps running (and keeps feeding the bubble's progress ring)
// after the overlay closes. `removed` is the terminal 410 the file tile renders as "no longer
// available"; `done` lingers briefly as the ring's finished flourish, then the entry is dropped.
export interface DownloadState {
  received: number;
  total: number;
  phase: "fetching" | "done" | "removed";
}

interface DownloadsStore {
  active: Record<string, DownloadState>;
  start: (agent: string, attachment: ChatAttachment) => void;
}

// A finished download stays "done" this long before the store forgets it.
const DONE_LINGER_MS = 2500;

// Progress arrives per network chunk; only meaningful movement commits a render.
function progressStep(total: number): number {
  return Math.max(total / 100, 256 * 1024);
}

function without(
  active: Record<string, DownloadState>,
  id: string,
): Record<string, DownloadState> {
  return Object.fromEntries(
    Object.entries(active).filter(([key]) => key !== id),
  );
}

export const useDownloadsStore = create<DownloadsStore>((set, get) => ({
  active: {},
  start: (agent, attachment) => {
    const id = attachment.id;
    if (get().active[id]?.phase === "fetching") return;
    const total = attachment.size;
    set((state) => ({
      active: {
        ...state.active,
        [id]: { received: 0, total, phase: "fetching" },
      },
    }));
    const step = progressStep(total);
    downloadAttachment(agent, attachment, (bytes) => {
      set((state) => {
        const entry = state.active[id];
        if (entry?.phase !== "fetching") return state;
        if (bytes - entry.received < step && bytes < total) return state;
        return {
          active: { ...state.active, [id]: { ...entry, received: bytes } },
        };
      });
    }).then(
      (outcome) => {
        if (outcome === "cancelled") {
          set((state) => ({ active: without(state.active, id) }));
          return;
        }
        set((state) => ({
          active: {
            ...state.active,
            [id]: { received: total, total, phase: "done" },
          },
        }));
        useToastStore
          .getState()
          .show("success", `downloaded ${attachment.name}`);
        window.setTimeout(() => {
          set((state) =>
            state.active[id]?.phase === "done"
              ? { active: without(state.active, id) }
              : state,
          );
        }, DONE_LINGER_MS);
      },
      (error: unknown) => {
        if (attachmentRemoved(error)) {
          set((state) => ({
            active: {
              ...state.active,
              [id]: { received: 0, total, phase: "removed" },
            },
          }));
          useToastStore
            .getState()
            .show("error", `${attachment.name} is no longer available`);
          return;
        }
        set((state) => ({ active: without(state.active, id) }));
        useToastStore
          .getState()
          .show("error", `couldn't download ${attachment.name}`);
      },
    );
  },
}));

// The live download state for one attachment, or null when it is idle.
export function useDownload(id: string): DownloadState | null {
  return useDownloadsStore((state) => state.active[id] ?? null);
}

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatAttachment } from "@vesta/core";

// A controllable download: each call captures its onProgress plus a deferred we resolve/reject by
// hand, so the test drives progress and completion deterministically.
const downloads = vi.hoisted(() => ({
  calls: [] as {
    onProgress?: (received: number, total: number) => void;
    resolve: (outcome: "saved" | "cancelled") => void;
    reject: (error: unknown) => void;
  }[],
}));
vi.mock("@/lib/download", () => ({
  downloadAttachment: (
    _agent: string,
    _attachment: ChatAttachment,
    onProgress?: (received: number, total: number) => void,
  ) =>
    new Promise<"saved" | "cancelled">((resolve, reject) => {
      downloads.calls.push({ onProgress, resolve, reject });
    }),
  attachmentRemoved: (error: unknown) => error === "removed",
}));

const toast = vi.hoisted(() => ({ show: vi.fn() }));
vi.mock("@/stores/use-toast", () => ({
  useToastStore: { getState: () => ({ show: toast.show }) },
}));

import { useDownloadsStore } from "./use-downloads";

const MB = 1024 * 1024;
const TOTAL = 100 * MB; // step = 1 MB, so sub-MB chunks are throttled out
const ATT: ChatAttachment = {
  id: "att-1",
  name: "beach.png",
  mime: "image/png",
  size: TOTAL,
};

function entry(id: string) {
  return useDownloadsStore.getState().active[id] ?? null;
}
function lastCall() {
  const call = downloads.calls.at(-1);
  if (!call) throw new Error("expected a download call");
  return call;
}
const flush = () => Promise.resolve();

beforeEach(() => {
  vi.useFakeTimers();
  downloads.calls.length = 0;
  toast.show.mockClear();
  useDownloadsStore.setState({ active: {} });
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useDownloadsStore", () => {
  it("throttles progress, completes with a success toast, then forgets the entry", async () => {
    useDownloadsStore.getState().start("ada", ATT);
    expect(entry("att-1")).toEqual({
      received: 0,
      total: TOTAL,
      phase: "fetching",
    });

    const call = lastCall();
    call.onProgress?.(500 * 1024, TOTAL); // below the 1 MB step
    expect(entry("att-1")?.received).toBe(0);
    call.onProgress?.(2 * MB, TOTAL);
    expect(entry("att-1")?.received).toBe(2 * MB);

    call.resolve("saved");
    await flush();
    expect(entry("att-1")).toEqual({
      received: TOTAL,
      total: TOTAL,
      phase: "done",
    });
    expect(toast.show).toHaveBeenCalledWith("success", "downloaded beach.png");

    vi.advanceTimersByTime(2500);
    expect(entry("att-1")).toBeNull();
  });

  it("ignores a second start while a download is already in flight", () => {
    useDownloadsStore.getState().start("ada", ATT);
    useDownloadsStore.getState().start("ada", ATT);
    expect(downloads.calls).toHaveLength(1);
  });

  it("keeps a removed attachment as a terminal tile", async () => {
    useDownloadsStore.getState().start("ada", ATT);
    lastCall().reject("removed");
    await flush();
    expect(entry("att-1")?.phase).toBe("removed");
    expect(toast.show).toHaveBeenCalledWith(
      "error",
      "beach.png is no longer available",
    );
  });

  it("clears the entry and toasts on a generic failure", async () => {
    useDownloadsStore.getState().start("ada", ATT);
    lastCall().reject(new Error("boom"));
    await flush();
    expect(entry("att-1")).toBeNull();
    expect(toast.show).toHaveBeenCalledWith(
      "error",
      "couldn't download beach.png",
    );
  });

  it("clears the entry silently when the save is cancelled", async () => {
    useDownloadsStore.getState().start("ada", ATT);
    lastCall().resolve("cancelled");
    await flush();
    expect(entry("att-1")).toBeNull();
    expect(toast.show).not.toHaveBeenCalled();
  });
});

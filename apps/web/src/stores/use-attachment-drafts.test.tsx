import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { ChatAttachment, UploadCallbacks, UploadMeta } from "@vesta/core";
import { MAX_ATTACHMENT_BYTES, UploadError } from "@vesta/core";
import { useToastStore } from "@/stores/use-toast";
import { useAttachmentDrafts } from "./use-attachment-drafts";

interface FakeUpload {
  meta: UploadMeta;
  callbacks: UploadCallbacks;
  finish: (attachment: ChatAttachment) => void;
  fail: (error: unknown) => void;
  aborted: boolean;
}

const uploads: FakeUpload[] = [];

vi.mock("@vesta/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@vesta/core")>();
  return {
    ...actual,
    uploadAttachment: (...args: Parameters<typeof actual.uploadAttachment>) => {
      const meta = args[1].meta;
      const callbacks = args[3];
      let finish!: (attachment: ChatAttachment) => void;
      let fail!: (error: unknown) => void;
      const result = new Promise<ChatAttachment>((resolve, reject) => {
        finish = resolve;
        fail = reject;
      });
      result.catch(() => undefined);
      const entry: FakeUpload = {
        meta,
        callbacks,
        finish,
        fail,
        aborted: false,
      };
      uploads.push(entry);
      return {
        result,
        abort: () => {
          entry.aborted = true;
          fail(new actual.UploadError("aborted"));
        },
      };
    },
  };
});

vi.mock("@/lib/connection", () => ({
  getConnection: () => ({ url: "https://gw.test", accessToken: "t" }),
}));
vi.mock("@/api/client", () => ({
  httpClient: { request: vi.fn(), json: vi.fn() },
}));

let agentCounter = 0;

function mount() {
  // A fresh agent per test keeps the module-level hold store cells isolated.
  agentCounter += 1;
  return renderHook(() => useAttachmentDrafts(`agent-${String(agentCounter)}`));
}

function file(
  name: string,
  size: number,
  type = "application/octet-stream",
): File {
  return new File([new Uint8Array(size)], name, { type });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

const DONE: ChatAttachment = {
  id: "srv1",
  name: "a.bin",
  mime: "application/octet-stream",
  size: 4,
};

describe("useAttachmentDrafts", () => {
  it("adds a file, tracks progress and waiting, and finalizes to ready", async () => {
    const { result } = mount();
    act(() => {
      result.current.addFiles([file("a.bin", 4)]);
    });
    await flush();

    expect(result.current.drafts[0]).toMatchObject({
      name: "a.bin",
      status: "uploading",
    });
    expect(result.current.ready).toBe(false);

    const upload = uploads.at(-1);
    if (!upload) throw new Error("engine not started");
    expect(upload.meta).toMatchObject({ name: "a.bin", size: 4 });

    act(() => {
      upload.callbacks.onProgress(2, 4);
    });
    expect(result.current.drafts[0]?.progress).toBe(0.5);

    act(() => {
      upload.callbacks.onStateChange("waiting");
    });
    expect(result.current.drafts[0]?.status).toBe("waiting");

    act(() => {
      upload.finish(DONE);
    });
    await flush();
    expect(result.current.drafts[0]).toMatchObject({
      status: "uploaded",
      attachment: DONE,
    });
    expect(result.current.ready).toBe(true);
    expect(result.current.uploaded).toEqual([DONE]);
  });

  it("marks a terminal failure and retries with a fresh engine run", async () => {
    const { result } = mount();
    act(() => {
      result.current.addFiles([file("b.bin", 4)]);
    });
    await flush();
    const first = uploads.at(-1);
    if (!first) throw new Error("engine not started");

    act(() => {
      first.fail(new UploadError("failed"));
    });
    await flush();
    expect(result.current.drafts[0]).toMatchObject({
      status: "error",
      error: "failed",
    });

    const before = uploads.length;
    act(() => {
      result.current.retry(result.current.drafts[0]?.localId ?? "");
    });
    await flush();
    expect(uploads.length).toBe(before + 1);
    expect(result.current.drafts[0]?.status).toBe("uploading");
  });

  it("rejects an oversized file with a toast and never starts an upload", async () => {
    const { result } = mount();
    const before = uploads.length;
    act(() => {
      result.current.addFiles([file("huge.bin", MAX_ATTACHMENT_BYTES + 1)]);
    });
    await flush();
    expect(result.current.drafts).toEqual([]);
    expect(uploads.length).toBe(before);
    expect(useToastStore.getState().current?.title).toContain("too large");
  });

  it("removes the draft with a toast when the agent lacks the routes", async () => {
    const { result } = mount();
    act(() => {
      result.current.addFiles([file("c.bin", 4)]);
    });
    await flush();
    act(() => {
      uploads.at(-1)?.fail(new UploadError("unsupported_agent"));
    });
    await flush();
    expect(result.current.drafts).toEqual([]);
    expect(useToastStore.getState().current?.title).toContain("update");
  });

  it("remove aborts an in-flight upload and clear empties everything", async () => {
    const { result } = mount();
    act(() => {
      result.current.addFiles([file("d.bin", 4), file("e.bin", 4)]);
    });
    await flush();
    const firstUpload = uploads.at(-2);
    if (!firstUpload) throw new Error("engine not started");

    act(() => {
      result.current.remove(result.current.drafts[0]?.localId ?? "");
    });
    await flush();
    expect(firstUpload.aborted).toBe(true);
    expect(result.current.drafts).toHaveLength(1);

    act(() => {
      result.current.clear();
    });
    expect(result.current.drafts).toEqual([]);
  });
});

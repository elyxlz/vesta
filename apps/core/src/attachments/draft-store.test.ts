import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatAttachment } from "./attachment-model";
import { MAX_ATTACHMENT_BYTES } from "./attachment-model";
import type { UploadCallbacks, UploadMeta } from "./upload";
import type { DraftAttachment } from "./attachment-draft";
import { createKeyedHoldStore } from "../holds/keyed-hold";
import type { HttpClient } from "../transport/http";

interface FakeUpload {
  meta: UploadMeta;
  callbacks: UploadCallbacks;
  finish: (attachment: ChatAttachment) => void;
  fail: (error: unknown) => void;
  aborted: boolean;
}

const uploads = vi.hoisted(() => [] as FakeUpload[]);

vi.mock("./upload", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./upload")>();
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

import { UploadError } from "./upload";
import { createDraftStore, type DraftSource } from "./draft-store";

const http: HttpClient = {
  request: () => Promise.reject(new Error("unused")),
  json: () => Promise.reject(new Error("unused")),
};
const DONE: ChatAttachment = {
  id: "srv1",
  name: "a.bin",
  mime: "application/octet-stream",
  size: 4,
};
const KEY = "ada@gw";

function source(
  name: string,
  size: number,
  overrides: Partial<DraftSource> = {},
): DraftSource {
  return {
    name,
    mime: "application/octet-stream",
    size,
    open: () => Promise.resolve(new Blob([new Uint8Array(size)])),
    ...overrides,
  };
}

function harness() {
  const hold = createKeyedHoldStore<DraftAttachment[]>();
  const notices: string[] = [];
  const revoked: string[] = [];
  let nextId = 0;
  const store = createDraftStore({
    http,
    hold,
    connectivity: { isOnline: () => true, onChange: () => () => undefined },
    makeId: () => {
      nextId += 1;
      return `local-${String(nextId)}`;
    },
    notify: (message) => notices.push(message),
    revokePreview: (url) => revoked.push(url),
  });
  const list = () => hold.read(KEY) ?? [];
  return { store, hold, notices, revoked, list };
}

const settle = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
};

beforeEach(() => {
  uploads.length = 0;
});

describe("createDraftStore", () => {
  it("adds a source, tracks progress and waiting, and finalizes to ready", async () => {
    const h = harness();
    expect(h.store.add(KEY, "ada", source("a.bin", 4))).toBe(true);
    expect(h.list()[0]).toMatchObject({ name: "a.bin", status: "uploading" });
    await settle();

    const upload = uploads.at(-1);
    if (!upload) throw new Error("engine not started");
    expect(upload.meta).toMatchObject({ name: "a.bin", size: 4 });

    upload.callbacks.onProgress(2, 4);
    expect(h.list()[0]?.progress).toBe(0.5);
    upload.callbacks.onStateChange("waiting");
    expect(h.list()[0]?.status).toBe("waiting");

    upload.finish(DONE);
    await settle();
    expect(h.list()[0]).toMatchObject({ status: "uploaded", attachment: DONE });
  });

  it("folds the probe into the upload meta", async () => {
    const h = harness();
    h.store.add(
      KEY,
      "ada",
      source("pic.jpg", 4, {
        mime: "image/jpeg",
        probe: () => Promise.resolve({ width: 640, height: 480 }),
      }),
    );
    await settle();
    expect(uploads.at(-1)?.meta).toMatchObject({ width: 640, height: 480 });
  });

  it("refuses a file over the size limit with a notice and keeps taking the rest", () => {
    const h = harness();
    expect(
      h.store.add(KEY, "ada", source("huge", MAX_ATTACHMENT_BYTES + 1)),
    ).toBe(true);
    expect(h.list()).toHaveLength(0);
    expect(h.notices[0]).toContain("too large");
  });

  it("refuses past the per-message cap and tells the caller to stop", () => {
    const h = harness();
    for (let i = 0; i < 10; i += 1)
      expect(h.store.add(KEY, "ada", source(`f${String(i)}`, 1))).toBe(true);
    expect(h.store.add(KEY, "ada", source("one-too-many", 1))).toBe(false);
    expect(h.notices.at(-1)).toContain("at most");
  });

  it("removing a draft aborts its upload and revokes its preview", async () => {
    const h = harness();
    h.store.add(KEY, "ada", source("a.bin", 4, { preview: "blob:one" }));
    await settle();
    expect(h.store.previewUrl("local-1")).toBe("blob:one");
    h.store.remove(KEY, "local-1");
    expect(uploads[0]?.aborted).toBe(true);
    expect(h.revoked).toEqual(["blob:one"]);
    expect(h.list()).toHaveLength(0);
    expect(h.store.previewUrl("local-1")).toBeNull();
  });

  it("marks a retryable failure failed and retries from the kept source", async () => {
    const h = harness();
    h.store.add(KEY, "ada", source("a.bin", 4));
    await settle();
    uploads[0]?.fail(new UploadError("failed"));
    await settle();
    expect(h.list()[0]).toMatchObject({ status: "error", error: "failed" });

    h.store.retry(KEY, "ada", "local-1");
    expect(h.list()[0]).toMatchObject({ status: "uploading", progress: 0 });
    await settle();
    expect(uploads).toHaveLength(2);
  });

  it("discards the draft with a notice when the agent cannot receive files", async () => {
    const h = harness();
    h.store.add(KEY, "ada", source("a.bin", 4));
    await settle();
    uploads[0]?.fail(new UploadError("unsupported_agent"));
    await settle();
    expect(h.list()).toHaveLength(0);
    expect(h.notices[0]).toContain("needs an update");
  });

  it("discards the draft with a notice when the source cannot be read", async () => {
    const h = harness();
    h.store.add(
      KEY,
      "ada",
      source("gone.bin", 4, { open: () => Promise.reject(new Error("io")) }),
    );
    await settle();
    expect(h.list()).toHaveLength(0);
    expect(h.notices[0]).toContain("couldn't read gone.bin");
    expect(uploads).toHaveLength(0);
  });

  it("aborts and frees an upload whose cell vanished from under it", async () => {
    const h = harness();
    h.store.add(KEY, "ada", source("a.bin", 4));
    await settle();
    h.hold.persist(KEY, []);
    uploads[0]?.callbacks.onProgress(1, 4);
    expect(uploads[0]?.aborted).toBe(true);
  });

  it("clear releases every draft in the cell", async () => {
    const h = harness();
    h.store.add(KEY, "ada", source("a.bin", 4));
    h.store.add(KEY, "ada", source("b.bin", 4));
    await settle();
    h.store.clear(KEY);
    expect(uploads.map((u) => u.aborted)).toEqual([true, true]);
    expect(h.list()).toHaveLength(0);
  });
});

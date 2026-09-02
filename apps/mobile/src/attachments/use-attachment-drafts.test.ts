import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatAttachment, UploadCallbacks, UploadMeta } from "@vesta/core";

interface FakeUpload {
  meta: UploadMeta;
  callbacks: UploadCallbacks;
  finish: (attachment: ChatAttachment) => void;
  fail: (error: unknown) => void;
  aborted: boolean;
}

const uploads = vi.hoisted(() => [] as FakeUpload[]);
const blobFailures = vi.hoisted(() => new Set<string>());
const MAX = 512 * 1024 * 1024;

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
vi.mock("./connectivity", () => ({
  netInfoConnectivity: () => ({
    isOnline: () => true,
    onChange: () => () => undefined,
  }),
}));
vi.mock("./pick", () => ({
  assetToBlob: (asset: { uri: string; name: string }) => {
    if (blobFailures.has(asset.name))
      return Promise.reject(new Error("unreadable"));
    const size = asset.name.startsWith("huge")
      ? 512 * 1024 * 1024 + 1
      : asset.name.length;
    // A shape-faithful stand-in: only `size` and sliceability matter to the engine.
    return Promise.resolve({ size } as Blob);
  },
}));
vi.mock("expo-crypto", () => {
  let next = 0;
  return {
    randomUUID: () => {
      next += 1;
      return `local-${String(next)}`;
    },
  };
});

import { UploadError, type HttpClient } from "@vesta/core";
import { agentHolds } from "@/holds/agent-holds";
import { attachmentDraftActions } from "./use-attachment-drafts";
import type { PickedAsset } from "./pick";

const http: HttpClient = {
  request: () => Promise.reject(new Error("unused")),
  json: () => Promise.reject(new Error("unused")),
};
const DONE: ChatAttachment = {
  id: "srv1",
  name: "a.bin",
  mime: "application/octet-stream",
  size: 5,
};

let holdCounter = 0;
let notices: string[] = [];

function mount() {
  // A fresh hold key per test keeps the module-level cell state isolated.
  holdCounter += 1;
  const key = `hold-${String(holdCounter)}`;
  const actions = attachmentDraftActions("apollo", key, http, (message) =>
    notices.push(message),
  );
  return { actions, drafts: () => agentHolds.attachments.read(key) ?? [], key };
}

function asset(name: string, mime = "application/octet-stream"): PickedAsset {
  return { uri: `file:///tmp/${name}`, name, mime };
}

async function flush() {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

beforeEach(() => {
  uploads.length = 0;
  blobFailures.clear();
  notices = [];
});

describe("attachment draft actions", () => {
  it("adds an asset, tracks progress and waiting, and finalizes", async () => {
    const { actions, drafts } = mount();
    await actions.addAssets([asset("a.bin")]);

    expect(drafts()[0]).toMatchObject({ name: "a.bin", status: "uploading" });
    const upload = uploads.at(-1);
    if (!upload) throw new Error("engine not started");
    expect(upload.meta).toMatchObject({ name: "a.bin", size: 5 });

    upload.callbacks.onProgress(2, 5);
    expect(drafts()[0]?.progress).toBe(0.4);
    upload.callbacks.onStateChange("waiting");
    expect(drafts()[0]?.status).toBe("waiting");

    upload.finish(DONE);
    await flush();
    expect(drafts()[0]).toMatchObject({ status: "uploaded", attachment: DONE });
  });

  it("carries picked dimensions into the upload meta and keeps a preview uri", async () => {
    const { actions, drafts } = mount();
    await actions.addAssets([
      { ...asset("pic.j", "image/jpeg"), width: 640, height: 480 },
    ]);
    expect(uploads.at(-1)?.meta).toMatchObject({ width: 640, height: 480 });
    expect(actions.previewUri(drafts()[0]?.localId ?? "")).toBe(
      "file:///tmp/pic.j",
    );
  });

  it("rejects an oversized blob with a notice and never starts an upload", async () => {
    const { actions, drafts } = mount();
    const before = uploads.length;
    await actions.addAssets([asset("huge.bin")]);
    expect(drafts()).toEqual([]);
    expect(uploads.length).toBe(before);
    expect(notices[0]).toContain("too large");
    expect(notices[0]).toContain(`${String(MAX / (1024 * 1024))}.0 MB`);
  });

  it("skips an unreadable asset with a notice and keeps taking the rest", async () => {
    blobFailures.add("broken.bin");
    const { actions, drafts } = mount();
    await actions.addAssets([asset("broken.bin"), asset("ok.bin")]);
    expect(notices[0]).toContain("couldn't read broken.bin");
    expect(drafts()).toHaveLength(1);
    expect(drafts()[0]?.name).toBe("ok.bin");
  });

  it("marks a terminal failure and retries with a fresh engine run", async () => {
    const { actions, drafts } = mount();
    await actions.addAssets([asset("b.bin")]);
    uploads.at(-1)?.fail(new UploadError("failed"));
    await flush();
    expect(drafts()[0]).toMatchObject({ status: "error", error: "failed" });

    const before = uploads.length;
    actions.retry(drafts()[0]?.localId ?? "");
    await flush();
    expect(uploads.length).toBe(before + 1);
    expect(drafts()[0]?.status).toBe("uploading");
  });

  it("removes the draft with an update notice when the agent lacks the routes", async () => {
    const { actions, drafts } = mount();
    await actions.addAssets([asset("c.bin")]);
    uploads.at(-1)?.fail(new UploadError("unsupported_agent"));
    await flush();
    expect(drafts()).toEqual([]);
    expect(notices[0]).toContain("needs an update");
  });

  it("remove aborts an in-flight upload and clear empties everything", async () => {
    const { actions, drafts } = mount();
    await actions.addAssets([asset("d.bin"), asset("e.bin")]);
    const first = uploads.at(-2);
    if (!first) throw new Error("engine not started");

    actions.remove(drafts()[0]?.localId ?? "");
    await flush();
    expect(first.aborted).toBe(true);
    expect(drafts()).toHaveLength(1);

    actions.clear();
    expect(drafts()).toEqual([]);
  });

  it("an evicted cell's progress tick aborts the engine instead of resurrecting it", async () => {
    const { actions, key } = mount();
    await actions.addAssets([asset("f.bin")]);
    const upload = uploads.at(-1);
    if (!upload) throw new Error("engine not started");

    // Simulate LRU eviction: the cell vanishes while the engine still runs.
    agentHolds.attachments.persist(key, []);
    upload.callbacks.onProgress(1, 5);

    expect(upload.aborted).toBe(true);
    expect(agentHolds.attachments.read(key)).toEqual([]);
  });
});

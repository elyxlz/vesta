import { describe, expect, it } from "vitest";

import {
  addDraft,
  draftTotalBytes,
  draftsReady,
  failDraft,
  finalizeDraft,
  removeDraft,
  setDraftProgress,
  setDraftWaiting,
  uploadedAttachments,
  uploadedIds,
  type DraftAttachment,
} from "./attachment-draft";
import {
  MAX_ATTACHMENTS_PER_MESSAGE,
  type ChatAttachment,
} from "./attachment-model";

const FILE = { name: "photo.jpg", mime: "image/jpeg", size: 1000 };
const DONE: ChatAttachment = {
  id: "srv1",
  name: "photo.jpg",
  mime: "image/jpeg",
  size: 1000,
};

function drafts(): DraftAttachment[] {
  const added = addDraft([], FILE, "a");
  if (added === null) throw new Error("unexpected cap");
  return added;
}

describe("attachment drafts", () => {
  it("adds an uploading draft and enforces the per-message cap", () => {
    let list: DraftAttachment[] = [];
    for (let index = 0; index < MAX_ATTACHMENTS_PER_MESSAGE; index += 1) {
      const added = addDraft(list, FILE, `d${String(index)}`);
      expect(added).not.toBeNull();
      if (added) list = added;
    }
    expect(addDraft(list, FILE, "over")).toBeNull();
    expect(list[0]).toMatchObject({
      status: "uploading",
      progress: 0,
      name: "photo.jpg",
    });
  });

  it("tracks progress, waiting, and finalize", () => {
    let list = drafts();
    list = setDraftProgress(list, "a", 500, 1000);
    expect(list[0]).toMatchObject({ status: "uploading", progress: 0.5 });
    list = setDraftWaiting(list, "a");
    expect(list[0]?.status).toBe("waiting");
    list = setDraftProgress(list, "a", 750, 1000);
    expect(list[0]?.status).toBe("uploading"); // progress resumes the uploading state
    list = finalizeDraft(list, "a", DONE);
    expect(list[0]).toMatchObject({
      status: "uploaded",
      progress: 1,
      attachment: DONE,
    });
  });

  it("records terminal errors and removal", () => {
    let list = drafts();
    list = failDraft(list, "a", "too_large");
    expect(list[0]).toMatchObject({ status: "error", error: "too_large" });
    list = removeDraft(list, "a");
    expect(list).toEqual([]);
  });

  it("gates send on every draft being uploaded", () => {
    expect(draftsReady([])).toBe(false);
    let list = drafts();
    expect(draftsReady(list)).toBe(false);
    list = finalizeDraft(list, "a", DONE);
    expect(draftsReady(list)).toBe(true);
    const withPending = addDraft(list, FILE, "b");
    expect(withPending && draftsReady(withPending)).toBe(false);
  });

  it("collects uploaded ids, metadata, and total size", () => {
    let list = drafts();
    const more = addDraft(list, { ...FILE, size: 500 }, "b");
    if (more === null) throw new Error("unexpected cap");
    list = finalizeDraft(more, "a", DONE);
    expect(uploadedIds(list)).toEqual(["srv1"]);
    expect(uploadedAttachments(list)).toEqual([DONE]);
    expect(draftTotalBytes(list)).toBe(1500);
  });
});

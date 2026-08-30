import { describe, expect, it } from "vitest";

import {
  carriesFiles,
  dragEnded,
  dragEntered,
  dragLeft,
  isDragActive,
} from "./drop-zone-model";

describe("drop zone counter", () => {
  it("stays active across child enter/leave pairs and hides on the final leave", () => {
    let depth = 0;
    depth = dragEntered(depth); // enter the chat
    depth = dragEntered(depth); // enter a child bubble
    depth = dragLeft(depth); // leave the child
    expect(isDragActive(depth)).toBe(true);
    depth = dragLeft(depth); // leave the chat
    expect(isDragActive(depth)).toBe(false);
  });

  it("never goes negative and resets on drop", () => {
    expect(dragLeft(0)).toBe(0);
    expect(dragEnded()).toBe(0);
    expect(isDragActive(dragEnded())).toBe(false);
  });

  it("only file drags count", () => {
    expect(carriesFiles(["Files"])).toBe(true);
    expect(carriesFiles(["text/plain", "text/uri-list"])).toBe(false);
    expect(carriesFiles([])).toBe(false);
  });
});

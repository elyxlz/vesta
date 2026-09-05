import { describe, expect, it } from "vitest";

import {
  attachmentKind,
  chatAttachmentPath,
  formatBytes,
} from "./attachment-model";

describe("attachmentKind", () => {
  it.each([
    ["image/jpeg", "image"],
    ["image/svg+xml", "image"],
    ["video/mp4", "video"],
    ["audio/mpeg", "audio"],
    ["application/pdf", "file"],
    ["text/plain", "file"],
    ["", "file"],
  ])("maps %s to %s", (mime, kind) => {
    expect(attachmentKind(mime)).toBe(kind);
  });
});

describe("formatBytes", () => {
  it.each([
    [0, "0 B"],
    [340, "340 B"],
    [1023, "1023 B"],
    [2 * 1024, "2.0 kB"],
    [Math.round(2.1 * 1024 * 1024), "2.1 MB"],
    [3 * 1024 * 1024 * 1024, "3.0 GB"],
  ])("formats %d as %s", (size, formatted) => {
    expect(formatBytes(size)).toBe(formatted);
  });
});

describe("chatAttachmentPath", () => {
  it("builds the proxied service subpath with encoding", () => {
    expect(chatAttachmentPath("my agent", "abc123")).toBe(
      "/agents/my%20agent/chat/attachments/abc123",
    );
  });

  it("appends the download flag", () => {
    expect(chatAttachmentPath("a", "x", true)).toBe(
      "/agents/a/chat/attachments/x?download=1",
    );
  });
});

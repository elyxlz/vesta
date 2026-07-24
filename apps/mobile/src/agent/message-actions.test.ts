import { describe, expect, it } from "vitest";
import { messageActionIds, quotedReply } from "./message-actions";

describe("message actions", () => {
  it("offers sender actions for a user message", () => {
    expect(
      messageActionIds({ user: true, canSpeak: false }),
    ).toEqual(["reply", "copy", "edit-resend", "share"]);
  });

  it("offers read aloud only for an agent message with speech enabled", () => {
    expect(
      messageActionIds({ user: false, canSpeak: true }),
    ).toEqual(["reply", "copy", "read-aloud", "share"]);
  });
});

describe("quotedReply", () => {
  it("quotes every line and leaves room for a reply", () => {
    expect(quotedReply(" First line\nSecond line ")).toBe(
      "> First line\n> Second line\n\n",
    );
  });
});

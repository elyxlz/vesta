import { describe, it, expect } from "vitest";
import { rightSlot } from "./right-slot";

describe("the composer's right slot", () => {
  it("offers a conversation when there is nothing to send", () => {
    expect(rightSlot({ input: "", recordingMode: null })).toBe("conversation");
    expect(rightSlot({ input: "   ", recordingMode: null })).toBe(
      "conversation",
    );
  });

  it("offers send once a draft exists", () => {
    expect(rightSlot({ input: "hi", recordingMode: null })).toBe("send");
  });

  it("stays on conversation while one is active, draft or not", () => {
    expect(rightSlot({ input: "hi", recordingMode: "conversation" })).toBe(
      "conversation",
    );
  });
});

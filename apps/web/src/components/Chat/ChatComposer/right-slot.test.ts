import { describe, it, expect } from "vitest";
import { rightSlot } from "./right-slot";

describe("the composer's right slot", () => {
  it("offers a conversation when there is nothing to send", () => {
    expect(
      rightSlot({ input: "", recordingMode: null, hasAttachments: false }),
    ).toBe("conversation");
    expect(
      rightSlot({ input: "   ", recordingMode: null, hasAttachments: false }),
    ).toBe("conversation");
  });

  it("offers send once a draft exists", () => {
    expect(
      rightSlot({ input: "hi", recordingMode: null, hasAttachments: false }),
    ).toBe("send");
  });

  it("offers send when attachment chips exist without a caption", () => {
    expect(
      rightSlot({ input: "", recordingMode: null, hasAttachments: true }),
    ).toBe("send");
  });

  it("stays on conversation while one is active, draft or not", () => {
    expect(
      rightSlot({
        input: "hi",
        recordingMode: "conversation",
        hasAttachments: true,
      }),
    ).toBe("conversation");
  });
});

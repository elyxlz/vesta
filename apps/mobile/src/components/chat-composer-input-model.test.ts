import { describe, expect, it } from "vitest";
import { shouldAcceptComposerTextChange } from "./chat-composer-input-model";

describe("native chat composer changes", () => {
  it("accepts edits and intentional clears while the field is interactive", () => {
    expect(shouldAcceptComposerTextChange(true, "draft", "draft edit")).toBe(
      true,
    );
    expect(shouldAcceptComposerTextChange(true, "draft", "")).toBe(true);
  });

  it("rejects a native host reset while the field is not interactive", () => {
    expect(shouldAcceptComposerTextChange(false, "keep me", "")).toBe(false);
  });

  it("allows a lifecycle no-op synchronization", () => {
    expect(shouldAcceptComposerTextChange(false, "draft", "draft")).toBe(true);
  });
});

import { describe, expect, it } from "vitest";
import {
  CHAT_LATEST_THRESHOLD,
  getLatestMessageOffset,
  isNearLatestMessage,
} from "./chat-scroll-model";

describe("chat scroll model", () => {
  it("uses the dynamic inverted-list inset as the iOS latest-message offset", () => {
    expect(getLatestMessageOffset("ios", 294)).toBe(-294);
  });

  it("keeps the Android latest-message offset at zero", () => {
    expect(getLatestMessageOffset("android", 294)).toBe(0);
  });

  it("only considers the list latest within the configured threshold", () => {
    const latestOffset = -294;

    expect(
      isNearLatestMessage(
        latestOffset + CHAT_LATEST_THRESHOLD,
        latestOffset,
      ),
    ).toBe(true);
    expect(
      isNearLatestMessage(
        latestOffset + CHAT_LATEST_THRESHOLD + 1,
        latestOffset,
      ),
    ).toBe(false);
  });
});

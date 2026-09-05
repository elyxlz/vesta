import { describe, expect, it } from "vitest";
import {
  CHAT_LATEST_THRESHOLD,
  getLatestMessageOffset,
  isNearLatestMessage,
  shouldAnchorToLatest,
} from "./chat-scroll-model";

describe("anchoring the inverted list to the latest message", () => {
  const ready = {
    platform: "ios",
    hasContent: true,
    latestOffset: -100,
    atLatest: true,
    anchored: false,
  };

  it("waits until the inset and the content both exist", () => {
    expect(
      shouldAnchorToLatest({ ...ready, trigger: "inset", latestOffset: 0 }),
    ).toBe(false);
    expect(
      shouldAnchorToLatest({ ...ready, trigger: "inset", hasContent: false }),
    ).toBe(false);
    expect(shouldAnchorToLatest({ ...ready, trigger: "inset" })).toBe(true);
  });

  it("re-anchors on content changes while at the latest message, but on an inset change only once", () => {
    expect(
      shouldAnchorToLatest({ ...ready, trigger: "content", anchored: true }),
    ).toBe(true);
    expect(
      shouldAnchorToLatest({ ...ready, trigger: "inset", anchored: true }),
    ).toBe(false);
  });

  it("never pulls a reader who scrolled up back down", () => {
    expect(
      shouldAnchorToLatest({ ...ready, trigger: "content", atLatest: false }),
    ).toBe(false);
  });

  it("is an iOS-only correction", () => {
    expect(
      shouldAnchorToLatest({ ...ready, trigger: "content", platform: "android" }),
    ).toBe(false);
  });
});

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
      isNearLatestMessage(latestOffset + CHAT_LATEST_THRESHOLD, latestOffset),
    ).toBe(true);
    expect(
      isNearLatestMessage(
        latestOffset + CHAT_LATEST_THRESHOLD + 1,
        latestOffset,
      ),
    ).toBe(false);
  });
});

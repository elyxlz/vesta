import { describe, expect, it } from "vitest";
import {
  SWIPE_REPLY_TRIGGER_PX,
  swipeReplyArmed,
  swipeReplyOffset,
  swipeReplyProgress,
} from "./swipe-reply-gesture";

describe("swipe reply gesture model", () => {
  it("never moves the bubble left", () => {
    expect(swipeReplyOffset(-40)).toBe(0);
  });

  it("tracks the finger up to the trigger", () => {
    expect(swipeReplyOffset(30)).toBe(30);
    expect(swipeReplyOffset(SWIPE_REPLY_TRIGGER_PX)).toBe(
      SWIPE_REPLY_TRIGGER_PX,
    );
  });

  it("resists a drag past the trigger", () => {
    expect(swipeReplyOffset(SWIPE_REPLY_TRIGGER_PX + 100)).toBe(
      SWIPE_REPLY_TRIGGER_PX + 25,
    );
  });

  it("arms the reply only at the trigger", () => {
    expect(swipeReplyArmed(SWIPE_REPLY_TRIGGER_PX - 1)).toBe(false);
    expect(swipeReplyArmed(SWIPE_REPLY_TRIGGER_PX)).toBe(true);
  });

  it("disarms a drag that returns below the trigger", () => {
    const offset = swipeReplyOffset(SWIPE_REPLY_TRIGGER_PX + 40 - 60);
    expect(swipeReplyArmed(offset)).toBe(false);
  });

  it("fills the icon progress to one at the trigger", () => {
    expect(swipeReplyProgress(0)).toBe(0);
    expect(swipeReplyProgress(SWIPE_REPLY_TRIGGER_PX / 2)).toBe(0.5);
    expect(swipeReplyProgress(SWIPE_REPLY_TRIGGER_PX + 20)).toBe(1);
  });
});

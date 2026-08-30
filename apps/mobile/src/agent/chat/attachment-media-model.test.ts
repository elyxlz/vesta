import { describe, expect, it } from "vitest";
import type { ChatAttachment } from "@vesta/core";
import {
  MEDIA_MAX_HEIGHT,
  MEDIA_MAX_WIDTH,
  mediaSize,
  throttledProgress,
} from "./attachment-media-model";

function attachment(width?: number, height?: number): ChatAttachment {
  return {
    id: "a",
    name: "pic.jpg",
    mime: "image/jpeg",
    size: 1000,
    width,
    height,
  };
}

describe("mediaSize", () => {
  it("scales a landscape photo down to the width cap, keeping aspect", () => {
    expect(mediaSize(attachment(4000, 3000))).toEqual({
      width: MEDIA_MAX_WIDTH,
      height: Math.round((MEDIA_MAX_WIDTH * 3000) / 4000),
    });
  });

  it("scales a tall portrait down to the height cap", () => {
    const size = mediaSize(attachment(1080, 2400));
    expect(size.height).toBe(MEDIA_MAX_HEIGHT);
    expect(size.width).toBe(Math.round((MEDIA_MAX_HEIGHT * 1080) / 2400));
  });

  it("never upscales a small image", () => {
    expect(mediaSize(attachment(120, 90))).toEqual({ width: 120, height: 90 });
  });

  it("falls back to a fixed footprint with no metadata dimensions", () => {
    expect(mediaSize(attachment())).toEqual({ width: 220, height: 150 });
  });
});

describe("throttledProgress", () => {
  it("holds until a meaningful step, then commits", () => {
    const total = 100 * 1024 * 1024;
    expect(throttledProgress(0, 1024, total)).toBe(0);
    expect(throttledProgress(0, total / 100, total)).toBe(total / 100);
  });

  it("always commits the final byte count", () => {
    expect(throttledProgress(90, 100, 100)).toBe(100);
  });
});

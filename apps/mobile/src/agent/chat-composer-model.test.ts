import { describe, expect, it } from "vitest";
import {
  clampComposerInputHeight,
  COMPOSER_BASE_HEIGHT,
  COMPOSER_INPUT_MAX_HEIGHT,
  COMPOSER_INPUT_MIN_HEIGHT,
  COMPOSER_SURFACE_PADDING,
} from "./chat-composer-model";

describe("chat composer sizing", () => {
  it("clamps measured content to the supported input range", () => {
    expect(clampComposerInputHeight(20)).toBe(COMPOSER_INPUT_MIN_HEIGHT);
    expect(clampComposerInputHeight(80)).toBe(80);
    expect(clampComposerInputHeight(240)).toBe(COMPOSER_INPUT_MAX_HEIGHT);
  });

  it("keeps the resting composer height aligned with its padding", () => {
    expect(COMPOSER_BASE_HEIGHT).toBe(
      COMPOSER_INPUT_MIN_HEIGHT + COMPOSER_SURFACE_PADDING * 2,
    );
  });
});

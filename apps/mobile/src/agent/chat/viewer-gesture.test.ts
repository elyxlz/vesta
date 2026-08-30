import { describe, expect, it } from "vitest";
import {
  DOUBLE_TAP_SCALE,
  ZOOM_MAX,
  clampPan,
  fittedSize,
  panBy,
  resetTransform,
  toggleZoom,
  zoomAt,
} from "./viewer-gesture";

const CONTAINER = { width: 400, height: 800 };
const CONTENT = { width: 400, height: 300 };

describe("viewer gesture model", () => {
  it("clamps zoom between fit and the max", () => {
    const zoomed = zoomAt(
      resetTransform(),
      { x: 0, y: 0 },
      100,
      CONTAINER,
      CONTENT,
    );
    expect(zoomed.scale).toBe(ZOOM_MAX);
    const under = zoomAt(zoomed, { x: 0, y: 0 }, 0.001, CONTAINER, CONTENT);
    expect(under.scale).toBe(1);
  });

  it("keeps the content point under the focal point while zooming", () => {
    // Focal at (100, 50) from center; after 2x the point under x stays anchored, while y snaps
    // back to centered because the doubled content is still shorter than the container.
    const next = zoomAt(
      resetTransform(),
      { x: 100, y: 50 },
      2,
      CONTAINER,
      CONTENT,
    );
    expect(next.x).toBe(-100);
    expect(next.y).toBeCloseTo(0);
  });

  it("clamps pan to the scaled overhang and centers the smaller axis", () => {
    const zoomed = { scale: 2, x: 0, y: 0 };
    const panned = panBy(zoomed, 5000, 5000, CONTAINER, CONTENT);
    // Width overhang: (400*2 - 400)/2 = 200. Height at 2x (600) < container 800: centered.
    expect(panned.x).toBe(200);
    expect(panned.y).toBe(0);
  });

  it("double-tap toggles between fit and the tap-anchored jump", () => {
    const zoomed = toggleZoom(
      resetTransform(),
      { x: 40, y: 0 },
      CONTAINER,
      CONTENT,
    );
    expect(zoomed.scale).toBe(DOUBLE_TAP_SCALE);
    expect(toggleZoom(zoomed, { x: 0, y: 0 }, CONTAINER, CONTENT)).toEqual(
      resetTransform(),
    );
  });

  it("clampPan is a no-op inside bounds", () => {
    const inside = { scale: 2, x: 10, y: 0 };
    expect(clampPan(inside, CONTAINER, CONTENT)).toEqual(inside);
  });

  it("fits media inside the container preserving aspect", () => {
    expect(fittedSize(CONTAINER, { width: 4000, height: 3000 })).toEqual({
      width: 400,
      height: 300,
    });
    expect(fittedSize(CONTAINER, { width: 0, height: 0 })).toEqual(CONTAINER);
  });
});

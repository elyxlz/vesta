import { describe, expect, it } from "vitest";

import {
  ZOOM_MAX,
  clampPan,
  panBy,
  resetZoom,
  toggleZoom,
  zoomAt,
} from "./viewer-zoom";

const CONTAINER = { width: 800, height: 600 };
const CONTENT = { width: 800, height: 600 }; // fitted content fills the container at scale 1

describe("viewer zoom", () => {
  it("zooms anchored at the cursor so the point under it stays put", () => {
    const cursor = { x: 200, y: -100 };
    const state = zoomAt(resetZoom(), cursor, 2, CONTAINER, CONTENT);
    expect(state.scale).toBe(2);
    // The content point that was at the cursor: c = (cursor - x)/scale must map back to cursor.
    const contentPoint = { x: (cursor.x - state.x) / state.scale, y: (cursor.y - state.y) / state.scale };
    expect(state.x + contentPoint.x * state.scale).toBeCloseTo(cursor.x);
    expect(state.y + contentPoint.y * state.scale).toBeCloseTo(cursor.y);
  });

  it("clamps the scale between fit and the max", () => {
    expect(zoomAt(resetZoom(), { x: 0, y: 0 }, 0.5, CONTAINER, CONTENT).scale).toBe(1);
    let state = resetZoom();
    for (let step = 0; step < 10; step += 1)
      state = zoomAt(state, { x: 0, y: 0 }, 2, CONTAINER, CONTENT);
    expect(state.scale).toBe(ZOOM_MAX);
  });

  it("clamps pan to the scaled content's overhang and centers smaller axes", () => {
    const zoomed = zoomAt(resetZoom(), { x: 0, y: 0 }, 2, CONTAINER, CONTENT);
    const panned = panBy(zoomed, 10_000, -10_000, CONTAINER, CONTENT);
    expect(panned.x).toBe((CONTENT.width * 2 - CONTAINER.width) / 2);
    expect(panned.y).toBe(-(CONTENT.height * 2 - CONTAINER.height) / 2);

    const narrow = { width: 200, height: 600 };
    const centered = clampPan({ scale: 1, x: 50, y: 0 }, CONTAINER, narrow);
    expect(centered.x).toBe(0); // content narrower than the container stays centered
  });

  it("double-click toggles fit and 2x", () => {
    const zoomed = toggleZoom(resetZoom(), { x: 100, y: 0 }, CONTAINER, CONTENT);
    expect(zoomed.scale).toBe(2);
    expect(toggleZoom(zoomed, { x: 100, y: 0 }, CONTAINER, CONTENT)).toEqual(resetZoom());
  });
});

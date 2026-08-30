// Pure zoom/pan math for the in-chat attachment viewer. The image renders fitted (object-contain)
// at scale 1 with a centered transform `translate(x, y) scale(scale)`; cursor coordinates are
// relative to the container's center. Zoom anchors the content point under the cursor, pan clamps
// so the content never detaches from the viewport.

export interface ZoomState {
  scale: number;
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

export const ZOOM_MAX = 4;
export const DOUBLE_CLICK_SCALE = 2;

export function resetZoom(): ZoomState {
  return { scale: 1, x: 0, y: 0 };
}

function clampValue(value: number, bound: number): number {
  return Math.min(bound, Math.max(-bound, value));
}

// Pan bounds: half the overhang of the scaled content beyond the container, per axis; content
// smaller than the container on an axis stays centered there.
export function clampPan(state: ZoomState, container: Size, content: Size): ZoomState {
  const boundX = Math.max(0, (content.width * state.scale - container.width) / 2);
  const boundY = Math.max(0, (content.height * state.scale - container.height) / 2);
  return { ...state, x: clampValue(state.x, boundX), y: clampValue(state.y, boundY) };
}

// Cursor-anchored zoom: the content point under the cursor stays put while the scale changes.
export function zoomAt(
  state: ZoomState,
  cursor: Point,
  factor: number,
  container: Size,
  content: Size,
): ZoomState {
  const scale = Math.min(ZOOM_MAX, Math.max(1, state.scale * factor));
  const ratio = scale / state.scale;
  const next = {
    scale,
    x: cursor.x - (cursor.x - state.x) * ratio,
    y: cursor.y - (cursor.y - state.y) * ratio,
  };
  return clampPan(next, container, content);
}

export function panBy(
  state: ZoomState,
  dx: number,
  dy: number,
  container: Size,
  content: Size,
): ZoomState {
  return clampPan({ ...state, x: state.x + dx, y: state.y + dy }, container, content);
}

// Double-click: zoomed in any amount returns to fit; fitted jumps to 2x anchored at the cursor.
export function toggleZoom(
  state: ZoomState,
  cursor: Point,
  container: Size,
  content: Size,
): ZoomState {
  if (state.scale > 1.01) return resetZoom();
  return zoomAt(state, cursor, DOUBLE_CLICK_SCALE, container, content);
}

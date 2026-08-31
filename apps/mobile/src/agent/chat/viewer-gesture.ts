// Pure zoom/pan math for the fullscreen attachment viewer, mirroring the web viewer's model. The
// image renders fitted at scale 1 with a centered transform `translate(x, y) scale(scale)`; focal
// coordinates are relative to the container's center. Zoom anchors the content point under the
// focal point, pan clamps so the content never detaches from the viewport. Every function is a
// worklet so the reanimated gesture handlers run it on the UI thread; in node the directive is
// inert and the suite exercises the same code.

export interface ViewerTransform {
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
export const DOUBLE_TAP_SCALE = 2;
// How far a scale-1 drag must travel down before release dismisses the viewer.
export const DISMISS_DRAG_PX = 90;

export function resetTransform(): ViewerTransform {
  "worklet";
  return { scale: 1, x: 0, y: 0 };
}

function clampValue(value: number, bound: number): number {
  "worklet";
  return Math.min(bound, Math.max(-bound, value));
}

// Pan bounds: half the overhang of the scaled content beyond the container, per axis; content
// smaller than the container on an axis stays centered there.
export function clampPan(
  transform: ViewerTransform,
  container: Size,
  content: Size,
): ViewerTransform {
  "worklet";
  const boundX = Math.max(
    0,
    (content.width * transform.scale - container.width) / 2,
  );
  const boundY = Math.max(
    0,
    (content.height * transform.scale - container.height) / 2,
  );
  return {
    scale: transform.scale,
    x: clampValue(transform.x, boundX),
    y: clampValue(transform.y, boundY),
  };
}

// Focal-anchored zoom: the content point under the focal point stays put while the scale changes.
export function zoomAt(
  transform: ViewerTransform,
  focal: Point,
  factor: number,
  container: Size,
  content: Size,
): ViewerTransform {
  "worklet";
  const scale = Math.min(ZOOM_MAX, Math.max(1, transform.scale * factor));
  const ratio = scale / transform.scale;
  return clampPan(
    {
      scale,
      x: focal.x - (focal.x - transform.x) * ratio,
      y: focal.y - (focal.y - transform.y) * ratio,
    },
    container,
    content,
  );
}

export function panBy(
  transform: ViewerTransform,
  dx: number,
  dy: number,
  container: Size,
  content: Size,
): ViewerTransform {
  "worklet";
  return clampPan(
    { scale: transform.scale, x: transform.x + dx, y: transform.y + dy },
    container,
    content,
  );
}

// Double-tap: zoomed in any amount returns to fit; fitted jumps to 2x anchored at the tap.
export function toggleZoom(
  transform: ViewerTransform,
  focal: Point,
  container: Size,
  content: Size,
): ViewerTransform {
  "worklet";
  if (transform.scale > 1.01) return resetTransform();
  return zoomAt(transform, focal, DOUBLE_TAP_SCALE, container, content);
}

// The size the media renders at when fitted (object-contain) inside the container.
export function fittedSize(container: Size, media: Size): Size {
  "worklet";
  if (media.width <= 0 || media.height <= 0) return container;
  const scale = Math.min(
    container.width / media.width,
    container.height / media.height,
  );
  return { width: media.width * scale, height: media.height * scale };
}

// Pure decision logic for the log render window: how many lines to render, when to grow
// the window as the user scrolls up, and whether the viewport sits at the tail. The Console
// and the gateway log viewer share it so both bound the DOM the same way, without any list
// virtualization. Kept separate from the hook so the decisions are unit-testable.

// The tail the viewer renders before the user scrolls, and the size it trims back to after
// settling at the bottom.
export const BASE_WINDOW_LINES = 300;
// Each grow renders this many more older lines from the buffer already in memory.
export const WINDOW_STEP_LINES = 300;
// Preload margin: within this many viewport heights of the top, the window grows, so more
// lines land before the user reaches the top of the rendered range.
export const LOAD_OLDER_SCREENS = 3;
// How close to the bottom (px) still counts as pinned, driving follow-on-append and the trim.
export const AT_BOTTOM_THRESHOLD_PX = 80;
// How long the viewport must sit at the bottom before the grown window trims back to the base.
export const SETTLE_MS = 30_000;

export interface WindowMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

export function distanceFromEnd(metrics: WindowMetrics): number {
  return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight;
}

export function isAtBottom(metrics: WindowMetrics): boolean {
  return distanceFromEnd(metrics) <= AT_BOTTOM_THRESHOLD_PX;
}

// Grow while older buffered lines remain unrendered and the viewport is within the preload
// margin of the top. Growing before the top is reached keeps native scroll anchoring away
// from scrollTop 0, where it stops holding position.
export function shouldGrow(
  metrics: WindowMetrics,
  hasHidden: boolean,
): boolean {
  return (
    hasHidden && metrics.scrollTop < metrics.clientHeight * LOAD_OLDER_SCREENS
  );
}

// One step larger, never past the buffered line count.
export function grownWindow(visibleCount: number, count: number): number {
  return Math.min(count, visibleCount + WINDOW_STEP_LINES);
}

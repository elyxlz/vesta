// Pure decision logic for the chat scroller: pinned-to-latest tracking, the follow latch
// for smooth scrolls to the end, load-older triggering, and prepend anchoring math.

// How close to the bottom (px) still counts as "pinned" — drives follow-on-append and
// gates the load-older check (don't page up while sitting at the bottom).
export const AT_BOTTOM_THRESHOLD_PX = 80;
// Preload margin: within this many viewport heights of the top, the previous page starts
// loading, so it lands before the user can reach the top of loaded history.
export const LOAD_OLDER_SCREENS = 3;
// Within this many px of the absolute top the user has outrun the fetch and is actually
// waiting on it — the only time the loading pill shows.
export const WAITING_AT_TOP_PX = 120;

export interface ScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

export function distanceFromEnd(metrics: ScrollMetrics): number {
  return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight;
}

// A smooth scroll to the latest message reports intermediate positions that read as "left
// the bottom" and would flash the scroll-to-bottom button on every append. The latch rides
// the animation by its one invariant (the distance to the end only shrinks) and hands
// control back the moment it lands or the user scrolls the other way.
export interface FollowLatch {
  following: boolean;
  lastDistance: number;
}

export const IDLE_LATCH: FollowLatch = { following: false, lastDistance: 0 };

export function startFollow(metrics: ScrollMetrics): FollowLatch {
  return { following: true, lastDistance: distanceFromEnd(metrics) };
}

export interface ScrollTick {
  // null = leave the pinned state unchanged (a follow animation is mid-flight).
  atBottom: boolean | null;
  loadOlder: boolean;
  nearTop: boolean;
  latch: FollowLatch;
}

export function onScrollTick(
  metrics: ScrollMetrics,
  latch: FollowLatch,
  canLoadOlder: boolean,
): ScrollTick {
  const distance = distanceFromEnd(metrics);
  const atEnd = distance <= AT_BOTTOM_THRESHOLD_PX;
  const nearTop = metrics.scrollTop < WAITING_AT_TOP_PX;
  if (latch.following && atEnd) {
    return { atBottom: true, loadOlder: false, nearTop, latch: IDLE_LATCH };
  }
  if (latch.following && distance <= latch.lastDistance) {
    return {
      atBottom: null,
      loadOlder: false,
      nearTop,
      latch: { following: true, lastDistance: distance },
    };
  }
  return {
    atBottom: atEnd,
    loadOlder:
      canLoadOlder &&
      !atEnd &&
      metrics.scrollTop < metrics.clientHeight * LOAD_OLDER_SCREENS,
    nearTop,
    latch: { following: false, lastDistance: distance },
  };
}

// Loading older history prepends rows above the viewport. Restoring scroll is exact, not
// estimated: capture the scroll state just before the rows land, then replay the height
// they added.
export interface PrependSnapshot {
  scrollTop: number;
  scrollHeight: number;
}

export function isPrepend(
  prevFirstKey: string | null,
  firstKey: string | null,
  prevCount: number,
  count: number,
): boolean {
  return prevCount > 0 && count > prevCount && firstKey !== prevFirstKey;
}

export function restoredScrollTop(
  snapshot: PrependSnapshot,
  scrollHeight: number,
): number {
  return snapshot.scrollTop + (scrollHeight - snapshot.scrollHeight);
}

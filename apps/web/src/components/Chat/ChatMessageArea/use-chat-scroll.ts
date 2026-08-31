import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import {
  IDLE_LATCH,
  captureMetrics,
  onResizeTick,
  onRowsChange,
  onScrollTick,
  restoredScrollTop,
  startFollow,
  type FollowLatch,
  type PrependSnapshot,
} from "./scroll";

interface ChatScrollArgs {
  parentRef: RefObject<HTMLDivElement | null>;
  count: number;
  firstKey: string | null;
  bottomInset: number;
  // A tall draft's extra scroll range, rendered outside the resize-observed content.
  bottomOverhang: number;
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
  // Fires when pinned-to-latest flips; drives the parent's scroll-to-bottom button.
  onAtBottomChange: (atBottom: boolean) => void;
}

// The one owner of the chat scroller's position: land the first page on the latest
// message, keep the prepended-history viewport still, follow appends while pinned,
// clear the composer inset, and track the pinned flag the button renders from.
export function useChatScroll({
  parentRef,
  count,
  firstKey,
  bottomInset,
  bottomOverhang,
  hasMore,
  loadingMore,
  loadMore,
  onAtBottomChange,
}: ChatScrollArgs) {
  // True while pinned near the latest message, false once the user scrolls up.
  // Recomputed on scroll and on content resize; the parent is notified only on change.
  const atBottomRef = useRef(true);
  const latchRef = useRef<FollowLatch>(IDLE_LATCH);
  // The scroll state as of the last scroll/resize tick. A prepend can only follow a
  // load-more, and a load-more only fires from a scroll tick, so this is always the
  // pre-prepend state the restore needs — captured in event handlers, never in render.
  const lastTickRef = useRef<PrependSnapshot>({
    scrollTop: 0,
    scrollHeight: 0,
  });
  const prevFirstKeyRef = useRef<string | null>(null);
  const prevCountRef = useRef(0);
  // True while the user sits at the very top of loaded history. Preloading means a fetch
  // usually finishes before they get here; the loading pill shows only when it didn't.
  const [nearTop, setNearTop] = useState(false);
  const setAtBottom = useCallback(
    (pinned: boolean) => {
      if (atBottomRef.current === pinned) return;
      atBottomRef.current = pinned;
      onAtBottomChange(pinned);
    },
    [onAtBottomChange],
  );

  // Position the scroller across data changes, before paint; onRowsChange decides.
  useLayoutEffect(() => {
    const el = parentRef.current;
    if (el) {
      const action = onRowsChange(
        prevFirstKeyRef.current,
        firstKey,
        prevCountRef.current,
        count,
        atBottomRef.current,
      );
      if (action === "restore") {
        el.scrollTop = restoredScrollTop(lastTickRef.current, el.scrollHeight);
      } else if (action === "jump") {
        el.scrollTop = el.scrollHeight;
      } else if (action === "follow") {
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
        latchRef.current = startFollow(el);
      }
      lastTickRef.current = captureMetrics(el);
    }
    prevFirstKeyRef.current = firstKey;
    prevCountRef.current = count;
  }, [count, firstKey, parentRef]);

  // The composer inset lands after the initial end-jump (its ResizeObserver is async) and
  // changes while a multi-line draft grows; while pinned, keep the latest message clear of it.
  useLayoutEffect(() => {
    const el = parentRef.current;
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [bottomInset, parentRef]);

  // The draft overhang grows the scroll range from outside the observed content div, so
  // neither a scroll nor a resize tick fires: refresh the prepend snapshot here, or a
  // later restore would replay the overhang's growth as if a prepend added it.
  useLayoutEffect(() => {
    const el = parentRef.current;
    if (el) lastTickRef.current = captureMetrics(el);
  }, [bottomOverhang, parentRef]);

  const handleScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    const metrics = captureMetrics(el);
    const tick = onScrollTick(
      metrics,
      latchRef.current,
      hasMore && !loadingMore,
    );
    latchRef.current = tick.latch;
    lastTickRef.current = metrics;
    setNearTop(tick.nearTop);
    if (tick.atBottom !== null) setAtBottom(tick.atBottom);
    if (tick.loadOlder) loadMore();
  }, [hasMore, loadingMore, loadMore, setAtBottom, parentRef]);

  // "At bottom" depends on content height, not just scroll position: growth beneath a pinned
  // viewport (a rewrap on resize, late fonts) moves the end without firing a scroll event.
  // onResizeTick decides: re-pin, land or re-aim a mid-flight follow, or recompute the flag.
  useLayoutEffect(() => {
    const el = parentRef.current;
    const content = el?.firstElementChild;
    if (!el || !content) return;
    const ro = new ResizeObserver(() => {
      let metrics = captureMetrics(el);
      const tick = onResizeTick(metrics, latchRef.current, atBottomRef.current);
      latchRef.current = tick.latch;
      if (tick.scrollToEnd) {
        el.scrollTo({ top: el.scrollHeight, behavior: tick.scrollToEnd });
        metrics = captureMetrics(el);
      }
      if (tick.atBottom !== null) setAtBottom(tick.atBottom);
      lastTickRef.current = metrics;
    });
    ro.observe(content);
    return () => ro.disconnect();
  }, [setAtBottom, parentRef]);

  const scrollToBottom = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    latchRef.current = startFollow(el);
  }, [parentRef]);

  // Instant, latch-free pin: lands flush and marks pinned, so the resize model's instant
  // re-pins take over from there. A smooth follow here would be re-aimed on every rewrap
  // tick of a live width resize and fling the viewport around.
  const pinToLatest = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    latchRef.current = IDLE_LATCH;
    setAtBottom(true);
  }, [parentRef, setAtBottom]);

  return {
    handleScroll,
    scrollToBottom,
    pinToLatest,
    waitingForOlder: loadingMore && nearTop,
  };
}

import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import {
  AT_BOTTOM_THRESHOLD_PX,
  IDLE_LATCH,
  isPrepend,
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

  // Position the scroller across data changes, before paint.
  useLayoutEffect(() => {
    const el = parentRef.current;
    if (el) {
      const prepend = isPrepend(
        prevFirstKeyRef.current,
        firstKey,
        prevCountRef.current,
        count,
      );
      if (prepend) {
        el.scrollTop = restoredScrollTop(lastTickRef.current, el.scrollHeight);
      } else if (count > 0 && prevCountRef.current === 0) {
        el.scrollTop = el.scrollHeight;
      } else if (count > prevCountRef.current && atBottomRef.current) {
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
        latchRef.current = startFollow(el);
      }
      lastTickRef.current = {
        scrollTop: el.scrollTop,
        scrollHeight: el.scrollHeight,
      };
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

  const handleScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    const tick = onScrollTick(el, latchRef.current, hasMore && !loadingMore);
    latchRef.current = tick.latch;
    lastTickRef.current = {
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
    };
    setNearTop(tick.nearTop);
    if (tick.atBottom !== null) setAtBottom(tick.atBottom);
    if (tick.loadOlder) loadMore();
  }, [hasMore, loadingMore, loadMore, setAtBottom, parentRef]);

  // "At bottom" depends on content height, not just scroll position: growth beneath a pinned
  // viewport (a rewrap on resize, late fonts) moves the end without firing a scroll event.
  // Re-pin, unless a follow animation is mid-flight and already owns the position.
  useLayoutEffect(() => {
    const el = parentRef.current;
    const content = el?.firstElementChild;
    if (!el || !content) return;
    const ro = new ResizeObserver(() => {
      if (latchRef.current.following) return;
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
      if (atBottomRef.current && dist > 1) {
        el.scrollTop = el.scrollHeight;
      } else {
        setAtBottom(dist <= AT_BOTTOM_THRESHOLD_PX);
      }
      lastTickRef.current = {
        scrollTop: el.scrollTop,
        scrollHeight: el.scrollHeight,
      };
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

  return {
    handleScroll,
    scrollToBottom,
    waitingForOlder: loadingMore && nearTop,
  };
}

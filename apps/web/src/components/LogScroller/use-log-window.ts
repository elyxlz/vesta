import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import {
  BASE_WINDOW_LINES,
  SETTLE_MS,
  grownWindow,
  isAtBottom,
  shouldGrow,
} from "@/lib/log-window";

interface LogWindowArgs {
  parentRef: RefObject<HTMLDivElement | null>;
  // Total buffered lines. `slice(-visibleCount)` renders the tail window of them.
  count: number;
  // The newest line's id. At the scrollback cap `count` stops changing while the tail keeps
  // advancing, so follow-on-append keys on this instead.
  newestId: number | undefined;
}

// The one owner of the log scroller's window and position, shared by the Console and the
// gateway log viewer. It renders only the tail window, grows it as the user scrolls up, and
// trims it back once they settle at the bottom, so the DOM stays bounded with no list
// virtualization. Native CSS scroll anchoring (overflow-anchor, left at its default on the
// scroller) holds the viewport still across a grow, a trim, and the rolling-cap front drop,
// so no manual restore math is needed; the hook writes the scroll position only to follow
// the tail while pinned.
export function useLogWindow({ parentRef, count, newestId }: LogWindowArgs) {
  const [visibleCount, setVisibleCount] = useState(BASE_WINDOW_LINES);
  const [atBottom, setAtBottom] = useState(true);
  const atBottomRef = useRef(true);

  const setPinned = useCallback((pinned: boolean) => {
    atBottomRef.current = pinned;
    setAtBottom((prev) => (prev === pinned ? prev : pinned));
  }, []);

  // A refilled list (agent switch/resume, viewer reopen) re-pins to the tail. Only the ref moves
  // here: the first append scrolls to the bottom, whose scroll event resyncs the state.
  useEffect(() => {
    if (count === 0) atBottomRef.current = true;
  }, [count]);

  // Follow the tail on append, land on the bottom when the buffer first fills, and re-pin
  // after a trim, unless the user scrolled up. Growing runs only while unpinned, so this
  // never fights an upward scroll.
  useLayoutEffect(() => {
    const el = parentRef.current;
    if (el && count > 0 && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [count, newestId, visibleCount, parentRef]);

  const onScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    const metrics = {
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    };
    setPinned(isAtBottom(metrics));
    if (shouldGrow(metrics, visibleCount < count)) {
      setVisibleCount((current) => grownWindow(current, count));
    }
  }, [parentRef, count, visibleCount, setPinned]);

  // Settling at the bottom trims the grown history back to the base tail. Scrolling up
  // regrows it through the ordinary path.
  useEffect(() => {
    if (!atBottom || visibleCount <= BASE_WINDOW_LINES) return;
    const timer = setTimeout(
      () => setVisibleCount(BASE_WINDOW_LINES),
      SETTLE_MS,
    );
    return () => clearTimeout(timer);
  }, [atBottom, visibleCount]);

  return { visibleCount, onScroll };
}

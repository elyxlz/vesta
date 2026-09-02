import { useCallback, useRef, type RefObject } from "react";
import { useLocation, useParams } from "react-router-dom";
import { Chat } from "@/components/Chat";
import { Dashboard } from "@/components/Dashboard";
import { useLayout } from "@/stores/use-layout";

interface MobileSwipeViewProps {
  scrollRef: RefObject<HTMLDivElement | null>;
  onScroll: () => void;
}

export function MobileSwipeView({ scrollRef, onScroll }: MobileSwipeViewProps) {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const bottomBarHeight = useLayout((s) => s.bottomBarHeight);
  const { name } = useParams<{ name: string }>();
  const location = useLocation();
  const isChat =
    location.pathname === `/agent/${encodeURIComponent(name ?? "")}/chat`;
  const mountedRef = useRef(false);

  // The first mount lands on the chat pane when that is the open route; a later route change
  // re-attaches the callback, and the mounted flag keeps it from scrolling again.
  const mountRef = useCallback(
    (node: HTMLDivElement | null) => {
      scrollRef.current = node;
      if (node && !mountedRef.current) {
        mountedRef.current = true;
        if (isChat) {
          node.scrollLeft = node.scrollWidth;
        }
      }
    },
    [scrollRef, isChat],
  );

  return (
    <div
      ref={mountRef}
      onScroll={onScroll}
      className="flex flex-1 min-h-0 overflow-x-auto snap-x snap-mandatory"
      style={{ WebkitOverflowScrolling: "touch", scrollbarWidth: "none" }}
    >
      <div
        className="w-full shrink-0 snap-center flex flex-col px-1"
        style={{
          paddingTop: navbarHeight,
          paddingBottom: `calc(${String(bottomBarHeight)}px + 0rem)`,
        }}
      >
        <Dashboard />
      </div>
      <div
        className="w-full shrink-0 snap-center flex flex-col"
        style={{
          paddingBottom: `calc(${String(bottomBarHeight)}px + 0.25rem)`,
        }}
      >
        <Chat fullscreen />
      </div>
    </div>
  );
}

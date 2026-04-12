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
    location.pathname === `/agent/${encodeURIComponent(name!)}/chat`;
  const isChatRef = useRef(isChat);
  isChatRef.current = isChat;
  const mountedRef = useRef(false);

  const mountRef = useCallback(
    (node: HTMLDivElement | null) => {
      (scrollRef as React.MutableRefObject<HTMLDivElement | null>).current =
        node;
      if (node && !mountedRef.current) {
        mountedRef.current = true;
        if (isChatRef.current) {
          node.scrollLeft = node.scrollWidth;
        }
      }
    },
    [scrollRef],
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
          paddingBottom: `calc(${bottomBarHeight}px + 0rem)`,
        }}
      >
        <Dashboard />
      </div>
      <div
        className="w-full shrink-0 snap-center flex flex-col px-3"
        style={{
          paddingBottom: `calc(${bottomBarHeight}px + 0.50rem)`,
        }}
      >
        <Chat fullscreen />
      </div>
    </div>
  );
}

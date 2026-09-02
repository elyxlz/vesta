import { motion } from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AgentCard } from "@/components/AgentCard";
import type { AgentRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  AGENT_CAROUSEL_GAP,
  AGENT_CAROUSEL_CARD_WIDTH,
  AGENT_CAROUSEL_EDGE_SCALE,
  AGENT_CAROUSEL_ITEM_STRIDE,
} from "./constants";
import { useDragScroll, type DragPhase } from "./use-drag-scroll";

const EDGE_FADE =
  "linear-gradient(to right, transparent, black 10%, black 90%, transparent)";

// The inline padding centers card 0 at scrollLeft 0, so a card's index is its
// scrollLeft in strides: the one position decision, read by the active dot,
// and every programmatic scroll.
function indexAt(scrollLeft: number) {
  return Math.round(scrollLeft / AGENT_CAROUSEL_ITEM_STRIDE);
}

// The scroller's custom properties feed the carousel-card CSS animation.
const SCROLLER_STYLE: React.CSSProperties = {
  gap: AGENT_CAROUSEL_GAP,
  paddingInline: `calc(50% - ${String(AGENT_CAROUSEL_CARD_WIDTH / 2)}px)`,
  overscrollBehaviorX: "none",
  touchAction: "pan-x",
  maskImage: EDGE_FADE,
  WebkitMaskImage: EDGE_FADE,
  "--carousel-stride": `${String(AGENT_CAROUSEL_ITEM_STRIDE)}px`,
  "--carousel-edge-scale": String(AGENT_CAROUSEL_EDGE_SCALE),
};

function Pagination({
  total,
  current,
  onGoto,
}: {
  total: number;
  current: number;
  onGoto: (index: number) => void;
}) {
  if (total <= 1) return null;

  return (
    <div className="flex justify-center gap-0 pt-4 absolute bottom-12 left-0 right-0">
      {Array.from({ length: total }, (_, i) => (
        <motion.button
          key={i}
          aria-label={`page ${String(i + 1)}`}
          className="grid size-10 place-items-center rounded-full"
          animate={{
            opacity: current === i ? 1 : 0.3,
            scale: current === i ? 1.4 : 1,
          }}
          onClick={() => onGoto(i)}
        >
          <span className="block size-1.5 rounded-full bg-muted-foreground" />
        </motion.button>
      ))}
    </div>
  );
}

export function AgentsCarousel({
  agents,
  initialIndex = -1,
}: {
  agents: AgentRow[];
  initialIndex?: number;
}) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [centeredIndex, setCenteredIndex] = useState(
    initialIndex > 0 ? initialIndex : 0,
  );
  // Mouse drag-to-scroll: snapping is off while dragging and through the smooth settle, so the
  // release glides to the nearest card instead of hard-snapping.
  const [phase, setPhase] = useState<DragPhase>("idle");
  useDragScroll(scrollerRef, AGENT_CAROUSEL_ITEM_STRIDE, setPhase);

  // Center initialIndex before paint, without animation.
  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (scroller && initialIndex > 0) {
      scroller.scrollLeft = initialIndex * AGENT_CAROUSEL_ITEM_STRIDE;
    }
  }, [initialIndex]);

  // The active dot follows the scroll, one state write per frame at most and
  // only when the index changes; the card scale is CSS on the scroll timeline.
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    let frame: number | null = null;
    const onScroll = () => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        setCenteredIndex(indexAt(scroller.scrollLeft));
      });
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, []);

  const gotoIndex = (index: number) => {
    scrollerRef.current?.scrollTo({
      left: index * AGENT_CAROUSEL_ITEM_STRIDE,
      behavior: "smooth",
    });
  };

  return (
    <div className="relative flex min-h-0 w-full flex-1">
      <div
        ref={scrollerRef}
        className={cn(
          "flex w-full items-center overflow-x-auto no-scrollbar",
          phase === "dragging" ? "cursor-grabbing select-none" : "cursor-grab",
        )}
        style={{
          ...SCROLLER_STYLE,
          scrollSnapType: phase === "idle" ? "x mandatory" : "none",
        }}
      >
        {agents.map((agent) => (
          <div
            key={agent.name}
            className="carousel-card flex shrink-0 items-center justify-center"
            style={{
              width: `${String(AGENT_CAROUSEL_CARD_WIDTH)}px`,
              aspectRatio: "1/1",
              scrollSnapAlign: "center",
            }}
          >
            <AgentCard agent={agent} />
          </div>
        ))}
      </div>
      <Pagination
        total={agents.length}
        current={centeredIndex}
        onGoto={gotoIndex}
      />
    </div>
  );
}

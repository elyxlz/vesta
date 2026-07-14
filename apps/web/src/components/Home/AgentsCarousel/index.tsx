import { motion } from "motion/react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { AgentCard } from "@/components/AgentCard";
import type { AgentInfo } from "@/lib/types";
import {
  AGENT_CAROUSEL_GAP,
  AGENT_CAROUSEL_CARD_WIDTH,
  scaleForCarouselItemOffset,
} from "./constants";

const EDGE_FADE =
  "linear-gradient(to right, transparent, black 10%, black 90%, transparent)";

// scrollLeft that places the card's center at the scroller's horizontal center.
function centerScrollLeft(scroller: HTMLDivElement, card: HTMLDivElement) {
  return card.offsetLeft + card.offsetWidth / 2 - scroller.clientWidth / 2;
}

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
          aria-label={`page ${i + 1}`}
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
  agents: AgentInfo[];
  initialIndex?: number;
}) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);
  const frameRef = useRef<number | null>(null);
  const [centeredIndex, setCenteredIndex] = useState(
    initialIndex > 0 ? initialIndex : 0,
  );

  // Scale every card by its distance to the scroller's horizontal center and
  // derive the centered index. Scale is written imperatively so per-frame
  // scroll updates never touch React state; only a changed centered index
  // re-renders (to flip enableTracking + the active pagination dot).
  const applyEffects = useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const viewportCenter = scroller.scrollLeft + scroller.clientWidth / 2;
    let nearestIndex = 0;
    let nearestDistance = Infinity;
    cardRefs.current.forEach((card, index) => {
      if (!card) return;
      const cardCenter = card.offsetLeft + card.offsetWidth / 2;
      const offset = cardCenter - viewportCenter;
      card.style.transform = `scale(${scaleForCarouselItemOffset(offset)})`;
      const distance = Math.abs(offset);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });
    setCenteredIndex((prev) => (prev === nearestIndex ? prev : nearestIndex));
  }, []);

  // Center initialIndex before paint, without animation.
  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    const card = cardRefs.current[initialIndex];
    if (scroller && card && initialIndex > 0) {
      scroller.scrollLeft = centerScrollLeft(scroller, card);
    }
    applyEffects();
  }, [applyEffects, initialIndex]);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;

    const onScroll = () => {
      if (frameRef.current !== null) return;
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null;
        applyEffects();
      });
    };

    const observer = new ResizeObserver(() => applyEffects());
    scroller.addEventListener("scroll", onScroll, { passive: true });
    observer.observe(scroller);

    return () => {
      scroller.removeEventListener("scroll", onScroll);
      observer.disconnect();
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [applyEffects]);

  const gotoIndex = (index: number) => {
    const scroller = scrollerRef.current;
    const card = cardRefs.current[index];
    if (!scroller || !card) return;
    scroller.scrollTo({
      left: centerScrollLeft(scroller, card),
      behavior: "smooth",
    });
  };

  return (
    <div className="relative flex min-h-0 w-full flex-1 items-center">
      <div
        ref={scrollerRef}
        className="flex w-full items-center overflow-x-auto no-scrollbar"
        style={{
          gap: AGENT_CAROUSEL_GAP,
          scrollSnapType: "x mandatory",
          paddingInline: `calc(50% - ${AGENT_CAROUSEL_CARD_WIDTH / 2}px)`,
          overscrollBehaviorX: "none",
          touchAction: "pan-x",
          maskImage: EDGE_FADE,
          WebkitMaskImage: EDGE_FADE,
        }}
      >
        {agents.map((agent, index) => (
          <div
            key={agent.name}
            ref={(el) => {
              cardRefs.current[index] = el;
            }}
            className="flex shrink-0 items-center justify-center"
            style={{
              width: `${AGENT_CAROUSEL_CARD_WIDTH}px`,
              aspectRatio: "1/1",
              scrollSnapAlign: "center",
            }}
          >
            <AgentCard agent={agent} enableTracking={index === centeredIndex} />
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

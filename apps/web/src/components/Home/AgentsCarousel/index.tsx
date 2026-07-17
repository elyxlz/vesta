import { motion, useMotionValueEvent, useTransform } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Carousel } from "@/lib/Carousel/index.mjs";
import { useCarousel } from "@/lib/Carousel/context.mjs";
import { useTicker } from "@/lib/Ticker/context.mjs";
import { useTickerItem } from "@/lib/Ticker/use-ticker-item.mjs";
import { AgentCard } from "@/components/AgentCard";
import type { AgentInfo } from "@/lib/types";
import {
  AGENT_CAROUSEL_GAP,
  AGENT_CAROUSEL_CARD_WIDTH,
  AGENT_CAROUSEL_ITEM_STRIDE,
  scaleForCarouselItemOffset,
} from "./constants";

function Pagination() {
  const { currentPage, totalPages, gotoPage } = useCarousel();

  if (totalPages <= 1) return null;

  return (
    <div className="flex justify-center gap-0 pt-4 absolute bottom-12 left-0 right-0">
      {Array.from({ length: totalPages }, (_, i) => (
        <motion.button
          key={i}
          aria-label={`page ${String(i + 1)}`}
          className="grid size-10 place-items-center rounded-full"
          animate={{
            opacity: currentPage === i ? 1 : 0.3,
            scale: currentPage === i ? 1.4 : 1,
          }}
          onClick={() => gotoPage(i)}
        >
          <span className="block size-1.5 rounded-full bg-muted-foreground" />
        </motion.button>
      ))}
    </div>
  );
}

// Centers the given item index with no animation, once the carousel has
// measured its items. On first mount the rendered offset is still "attached" to
// targetOffset, so setting targetOffset jumps instantly instead of springing.
// Runs a single time; horizontal axis means sign is 1.
function CenterOnMount({ index }: { index: number }) {
  const { targetOffset } = useCarousel();
  const { itemPositions, clampOffset } = useTicker();
  const centered = useRef(false);

  useEffect(() => {
    if (centered.current || index <= 0) return;
    const position = itemPositions[index];
    if (!position) return;
    centered.current = true;
    targetOffset.set(clampOffset(-position.start));
  }, [targetOffset, clampOffset, itemPositions, index]);

  return null;
}

function CarouselCard({ agent }: { agent: AgentInfo }) {
  const { offset } = useTickerItem();
  const [isCentered, setIsCentered] = useState(
    () => Math.abs(offset.get()) < AGENT_CAROUSEL_ITEM_STRIDE / 2,
  );

  const scale = useTransform(offset, scaleForCarouselItemOffset);

  useMotionValueEvent(offset, "change", (v) => {
    const centered = Math.abs(v) < AGENT_CAROUSEL_ITEM_STRIDE / 2;
    queueMicrotask(() => {
      setIsCentered((prev) => (prev === centered ? prev : centered));
    });
  });

  return (
    <motion.div
      className="flex h-full items-center justify-center"
      style={{
        width: `${String(AGENT_CAROUSEL_CARD_WIDTH)}px`,
        aspectRatio: "1/1",
        scale,
      }}
    >
      <AgentCard agent={agent} enableTracking={isCentered} />
    </motion.div>
  );
}

export function AgentsCarousel({
  agents,
  initialIndex = -1,
}: {
  agents: AgentInfo[];
  initialIndex?: number;
}) {
  const items = agents.map((agent) => (
    <CarouselCard key={agent.name} agent={agent} />
  ));

  return (
    <Carousel
      className="relative flex min-h-0 w-full flex-1 items-center"
      items={items}
      gap={AGENT_CAROUSEL_GAP}
      loop={false}
      snap="item"
      overflow
      fade="10%"
      transition={{ type: "spring", stiffness: 500, damping: 40 }}
      style={{
        cursor: "grab",
        paddingInline: `calc(50% - ${String(AGENT_CAROUSEL_CARD_WIDTH / 2)}px)`,
        touchAction: "pan-y",
        overscrollBehaviorX: "none",
      }}
    >
      <CenterOnMount index={initialIndex} />
      <Pagination />
    </Carousel>
  );
}

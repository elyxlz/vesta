import { motion, useMotionValueEvent, useTransform } from "motion/react";
import { useState } from "react";
import { Carousel } from "@/lib/Carousel/index.mjs";
import { useCarousel } from "@/lib/Carousel/context.mjs";
import { useTickerItem } from "@/lib/Ticker/use-ticker-item.mjs";
import { AgentCard } from "@/components/AgentCard";
import type { AgentInfo } from "@/lib/types";

export const AGENT_CAROUSEL_GAP = 16;
export const AGENT_CAROUSEL_CARD_WIDTH = 220;
export const AGENT_CAROUSEL_ITEM_STRIDE =
  AGENT_CAROUSEL_CARD_WIDTH + AGENT_CAROUSEL_GAP;

export function scaleForCarouselItemOffset(offsetPx: number) {
  const distance = Math.abs(offsetPx);
  return (
    1 - 0.15 * Math.min(distance / AGENT_CAROUSEL_ITEM_STRIDE, 1)
  );
}

function Pagination() {
  const { currentPage, totalPages, gotoPage } = useCarousel();

  if (totalPages <= 1) return null;

  return (
    <div className="flex justify-center gap-2 pt-4 absolute bottom-12 left-0 right-0">
      {Array.from({ length: totalPages }, (_, i) => (
        <motion.button
          key={i}
          className={"size-1.5 rounded-full bg-muted-foreground"}
          animate={{
            opacity: currentPage === i ? 1 : 0.3,
            scale: currentPage === i ? 1.4 : 1,
          }}
          onClick={() => gotoPage(i)}
        />
      ))}
    </div>
  );
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
      style={{ width: `${AGENT_CAROUSEL_CARD_WIDTH}px`, aspectRatio: "1/1", scale }}
    >
      <AgentCard agent={agent} enableTracking={isCentered} />
    </motion.div>
  );
}

export function AgentsCarousel({ agents }: { agents: AgentInfo[] }) {
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
        paddingInline: `calc(50% - ${AGENT_CAROUSEL_CARD_WIDTH / 2}px)`,
        touchAction: "pan-y",
        overscrollBehaviorX: "none",
      }}
    >
      <Pagination />
    </Carousel>
  );
}

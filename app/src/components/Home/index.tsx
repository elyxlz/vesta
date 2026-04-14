import { AnimatePresence, motion } from "motion/react";
import { useGateway } from "@/providers/GatewayProvider";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AgentsCarousel,
  AGENT_CAROUSEL_CARD_WIDTH,
  AGENT_CAROUSEL_GAP,
  AGENT_CAROUSEL_ITEM_STRIDE,
  scaleForCarouselItemOffset,
} from "./AgentsCarousel";
import { EmptyState } from "./EmptyState";

function SkeletonCard({
  index,
  opacity,
}: {
  index: number;
  opacity: number;
}) {
  const scale = scaleForCarouselItemOffset(
    index * AGENT_CAROUSEL_ITEM_STRIDE,
  );
  return (
    <motion.div
      className="flex shrink-0 items-center justify-center"
      style={{
        width: `${AGENT_CAROUSEL_CARD_WIDTH}px`,
        aspectRatio: "1/1",
        scale,
      }}
    >
      <Card
        className="flex h-full w-full items-center justify-center gap-3"
        style={{ opacity }}
      >
        <CardContent className="flex flex-col items-center gap-3 px-5 pt-0 pb-0">
          <Skeleton className="size-28 rounded-full" />
          <Skeleton className="h-6 w-24 rounded-lg" />
        </CardContent>
      </Card>
    </motion.div>
  );
}

const SKELETON_COUNT = 6;

function SkeletonList() {
  return (
    <motion.div
      key="skeletons"
      className="relative flex min-h-0 w-full flex-1 items-center"
      style={{
        gap: AGENT_CAROUSEL_GAP,
        paddingInline: `calc(50% - ${AGENT_CAROUSEL_CARD_WIDTH / 2}px)`,
      }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
    >
      {Array.from({ length: SKELETON_COUNT }, (_, i) => (
        <SkeletonCard
          key={i}
          index={i}
          opacity={1 - i / SKELETON_COUNT}
        />
      ))}
      <p className="absolute bottom-12 left-0 right-0 text-center text-sm text-muted-foreground">
        loading agents…
      </p>
    </motion.div>
  );
}

export function Home() {
  const { agentsFetched, agents } = useGateway();

  return (
    <AnimatePresence mode="wait">
      {!agentsFetched ? (
        <SkeletonList />
      ) : agents.length === 0 ? (
        <motion.div
          key="empty"
          className="flex min-h-0 w-full flex-1"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
        >
          <EmptyState />
        </motion.div>
      ) : (
        <motion.div
          key="agents"
          className="flex min-h-0 w-full flex-1"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
        >
          <AgentsCarousel agents={agents} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}

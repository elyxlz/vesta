import { AnimatePresence, motion } from "motion/react";
import { useGateway } from "@/providers/GatewayProvider";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AgentsCarousel } from "./AgentsCarousel";
import { EmptyState } from "./EmptyState";

function SkeletonCard({ opacity }: { opacity: number }) {
  return (
    <Card className="flex shrink-0 items-center justify-center w-[220px] aspect-square" style={{ opacity }}>
      <div className="flex flex-col items-center gap-3 px-5">
        <Skeleton className="size-28 rounded-full" />
        <Skeleton className="h-6 w-24 rounded-lg" />
      </div>
    </Card>
  );
}

const SKELETON_COUNT = 6;

function SkeletonList() {
  return (
    <motion.div
      key="skeletons"
      className="relative flex min-h-0 w-full flex-1 items-center gap-4 overflow-hidden"
      style={{ paddingLeft: "calc(50% - 110px)" }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
    >
      {Array.from({ length: SKELETON_COUNT }, (_, i) => (
        <SkeletonCard key={i} opacity={1 - i / SKELETON_COUNT} />
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

import { motion } from "motion/react";
import { Spinner } from "@/components/ui/spinner";
import { orbColors, type OrbVisualState } from "@/components/Orb/styles";

type DynamicIslandCollapsedProps = {
  name: string;
  operation: string;
  orbState: OrbVisualState;
  onExpand: () => void;
};

export function DynamicIslandCollapsed({
  name,
  operation,
  orbState,
  onExpand,
}: DynamicIslandCollapsedProps) {
  return (
    <div
      className="flex items-center gap-2.5 py-3 px-12 cursor-pointer touch-manipulation"
      onPointerDown={(event) => {
        if (event.pointerType === "touch") {
          onExpand();
        }
      }}
    >
      <motion.div
        className="rounded-full shrink-0"
        style={{ width: 14, height: 14, backgroundColor: orbColors[orbState][1] }}
        animate={{
          backgroundColor: orbColors[orbState][1],
          boxShadow: `0 0 8px 2px ${orbColors[orbState][1]}`,
        }}
        transition={{ duration: 1 }}
      />
      <div className="flex items-center gap-2">
        <span className="text-sm leading-tight font-semibold whitespace-nowrap">{name}</span>
        {operation !== "idle" && (
          <Spinner className="size-3 text-foreground/40" />
        )}
      </div>
    </div>
  );
}

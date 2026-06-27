import { motion } from "motion/react";
import { Orb } from "@/components/Orb";
import { CardDescription, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { OrbVisualState } from "@/components/Orb/styles";
import { useProvider } from "@/hooks/use-provider";
import { agentIslandContentTransition } from "./transitions";

type AgentIslandExpandedProps = {
  name: string;
  orbState: OrbVisualState;
  statusLabel: string;
  error: string;
};

export function AgentIslandExpanded({
  name,
  orbState,
  statusLabel,
  error,
}: AgentIslandExpandedProps) {
  const { provider } = useProvider(name);
  const model =
    provider && provider.kind !== "none" && provider.authed
      ? provider.model
      : null;
  return (
    <div className="relative -top-2 flex h-[168px] w-[168px] flex-col items-center justify-center gap-2 will-change-transform">
      <motion.div
        layoutId="agent-island-orb"
        layout
        className="flex shrink-0 items-center justify-center will-change-transform"
        transition={agentIslandContentTransition}
      >
        <Orb
          state={orbState}
          size={100}
          enableTracking
          label={`${name}: ${statusLabel || orbState}`}
        />
      </motion.div>
      <div className="-mt-4 flex flex-col items-center justify-center gap-1 text-center will-change-transform">
        <motion.div
          layoutId="agent-island-name"
          layout
          transition={agentIslandContentTransition}
          className="will-change-transform"
        >
          <CardTitle className="line-clamp-2 px-0.5 text-center font-serif text-base sm:text-lg font-medium leading-tight tracking-tight">
            {name}
          </CardTitle>
        </motion.div>
        <motion.div
          layoutId="agent-island-status"
          layout
          aria-live="polite"
          transition={agentIslandContentTransition}
          className="mt-0.5 will-change-transform"
        >
          <CardDescription
            className={cn(
              "line-clamp-3 w-full px-0.5 text-xs leading-snug",
              error ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {statusLabel}
          </CardDescription>
        </motion.div>
        {model && (
          <motion.span
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ ...agentIslandContentTransition, delay: 0.1 }}
            className="line-clamp-1 max-w-[150px] px-0.5 text-[10px] text-muted-foreground will-change-transform"
          >
            {model}
          </motion.span>
        )}
      </div>
    </div>
  );
}

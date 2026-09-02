import { AnimatePresence, motion } from "motion/react";
import {
  Card,
  CardContent,
  CardDescription,
  CardTitle,
} from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { Orb } from "@/components/Orb";
import type { AgentRow } from "@vesta/core";
import { useNavigate } from "react-router-dom";
import { useAgentVisualStatus } from "@vesta/core/react";
import { useOptionalController } from "@/providers/ControllerProvider/context";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

interface AgentCardProps {
  agent: AgentRow;
}

export function AgentCard({ agent }: AgentCardProps) {
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  const { orbState, label, request, error } = useAgentVisualStatus(
    useOptionalController(),
    agent,
    agent.activityState,
  );
  // Work vestad is running counts even when this tab did not start it.
  const inFlight = request !== "idle" || agent.operation !== null;

  return (
    <Card className="flex items-center justify-center h-full w-full">
      <button
        type="button"
        aria-label={`open ${agent.name}`}
        onClick={() => {
          void navigate(`/agent/${agent.name}${isMobile ? "/chat" : ""}`);
        }}
        className="flex h-full w-full items-center justify-center rounded-squircle-md border border-transparent [corner-shape:squircle] outline-none transition-all hover:bg-muted/40 active:scale-[0.99] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30"
      >
        <CardContent className="flex flex-col items-center gap-3 px-5 pt-0 pb-0">
          <span className="inline-flex">
            <Orb
              state={orbState}
              size={112}
              label={`${agent.name}: ${label}`}
            />
          </span>
          <CardTitle className="font-serif text-center text-2xl -mt-3 font-medium tracking-tight text-foreground">
            {agent.name}
          </CardTitle>

          <AnimatePresence>
            {(inFlight || error) && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.15 }}
                className="flex items-center gap-1.5"
              >
                {inFlight && (
                  <Spinner className="size-3 text-muted-foreground" />
                )}
                <CardDescription
                  className={cn(
                    "text-xs",
                    error ? "text-destructive" : "text-muted-foreground",
                  )}
                >
                  {error || label}
                </CardDescription>
              </motion.div>
            )}
          </AnimatePresence>
        </CardContent>
      </button>
    </Card>
  );
}

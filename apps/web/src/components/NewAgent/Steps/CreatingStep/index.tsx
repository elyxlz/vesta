import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Orb } from "@/components/Orb";
import { useGateway } from "@/providers/GatewayProvider";
import { fade, instant } from "@/lib/motion";
import { buildPhaseMessage } from "@/api/agents";

// One body for the whole birth: the same mounted orb works (busy), dims on a
// failure (off), and wakes up (alive). The action button and the error line
// live in the shell, not here.
export function CreatingStep({
  agentName,
  done,
  failed,
}: {
  agentName: string;
  done: boolean;
  failed: boolean;
}) {
  const { agents } = useGateway();
  const reduced = useReducedMotion() ?? false;
  // The build phase rides the replica tree: vestad records it into shared state
  // and the roster carries it, so the status line follows the real create with
  // no separate poll.
  const phase =
    agents.find((agent) => agent.name === agentName)?.buildPhase ?? null;

  const orbState = failed ? "off" : done ? "alive" : "busy";

  return (
    <div className="flex w-full flex-col items-center px-4">
      <Orb state={orbState} size={96} />
      <div className="mt-3 flex flex-col items-center gap-1 text-center">
        {done ? (
          <h2 className="text-base font-semibold leading-tight">
            {agentName} is ready
          </h2>
        ) : failed ? null : (
          <>
            <AnimatePresence mode="wait">
              <motion.p
                key={buildPhaseMessage(phase)}
                role="status"
                aria-live="polite"
                {...(reduced ? instant : fade)}
                className="text-xs text-muted-foreground"
              >
                {buildPhaseMessage(phase)}
              </motion.p>
            </AnimatePresence>
            <p className="text-xs text-muted-foreground">
              first setup can take several minutes.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

import { agentStatusLabel } from "@vesta/core";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Orb } from "@/components/Orb";
import { useGateway } from "@/providers/GatewayProvider";
import { fade, instant } from "@/lib/motion";
import { buildPhaseMessage } from "@/api/agents";

// One body for the whole birth: the same mounted orb works (busy), dims on a
// failure (off), and wakes up (alive). On a failure the orb is joined by a
// heading and the reason, so the screen explains itself; the retry button lives
// in the shell.
export function CreatingStep({
  agentName,
  stage,
  done,
  failed,
  error,
}: {
  agentName: string;
  stage: "creating" | "applying";
  done: boolean;
  failed: boolean;
  error?: string | null;
}) {
  const { agents } = useGateway();
  const reduced = useReducedMotion() ?? false;
  // The build phase rides the replica tree: vestad records it into shared state
  // and the roster carries it, so the status line follows the real create with
  // no separate poll.
  const agent = agents.find((candidate) => candidate.name === agentName);
  const phase = agent?.buildPhase ?? null;
  const applyingMessage =
    agent && agent.status !== "unprovisioned"
      ? agentStatusLabel(
          agent.status,
          agent.activityState,
          agent.operation,
          agent.booting,
          agent.rateLimited,
        )
      : "applying provider settings...";
  const progressMessage =
    stage === "creating" ? buildPhaseMessage(phase) : applyingMessage;

  const orbState = failed ? "off" : done ? "alive" : "busy";

  return (
    <div className="flex w-full flex-col items-center px-4">
      <Orb state={orbState} size={96} />
      <div className="mt-3 flex flex-col items-center gap-1 text-center font-serif">
        {done ? (
          <h2 className="text-base font-semibold leading-tight">
            {agentName} is ready
          </h2>
        ) : failed ? (
          <>
            <h2 className="text-base font-semibold leading-tight">
              couldn&apos;t{" "}
              {stage === "creating" ? "create" : "finish setting up"}{" "}
              {agentName}
            </h2>
            {error && <p className="text-xs text-destructive">{error}</p>}
          </>
        ) : (
          <>
            <AnimatePresence mode="wait">
              <motion.p
                key={progressMessage}
                role="status"
                aria-live="polite"
                {...(reduced ? instant : fade)}
                className="text-xs text-muted-foreground"
              >
                {progressMessage}
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
